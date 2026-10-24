/**
 * HubApiClient - 核心 HTTP 通信适配层
 * 严格遵循白名单端点：
 *   - GET  /api/state
 *   - GET  /health
 *   - POST /api/action
 *
 * 内存维护 userToken (Authorization: Bearer <token>) 与 selectedProjectId (X-Hub-Project)
 * 检查 POST 262,144 字节上限，先验 HTTP 状态码再解包 {error}，发送消息复用 request_key
 */

'use strict';

const MAX_PAYLOAD_BYTES = 262144; // 256 KB
const BLOCKED_INTERNAL_ACTIONS = new Set([
  'poll',
  'ack',
  'heartbeat',
  'progress',
  'project',
  'project_status',
  'project_assign',
  'project_complete',
  'project_mailbox',
  'project_set_role',
  'project_cancel_task',
  'project_return_manager',
  'report_result'
]);

class HubApiClient {
  /**
   * @param {Object} [options]
   * @param {string} [options.baseUrl] - Hub API 基础路径，默认当前 origin 或 http://127.0.0.1:8765
   * @param {string} [options.token] - 本地用户凭证（仅存内存）
   * @param {string} [options.projectId] - 初始选中的项目分组 ID
   */
  constructor(options = {}) {
    this.baseUrl = (options.baseUrl || '').replace(/\/+$/, '');
    this._userToken = options.token || '';
    this._selectedProjectId = options.projectId || '';
    this._pollSeq = 0;
  }

  // --- 凭证与项目状态（纯内存管理，禁止存入 localStorage/URL） ---

  setUserToken(token) {
    this._userToken = (token || '').trim();
  }

  getUserToken() {
    return this._userToken;
  }

  hasToken() {
    return Boolean(this._userToken);
  }

  clearUserToken() {
    this._userToken = '';
  }

  setSelectedProjectId(projectId) {
    this._selectedProjectId = (projectId || '').trim();
    // 切换项目时递增序列号，使在途旧项目响应失效
    this._pollSeq++;
    return this._pollSeq;
  }

  getSelectedProjectId() {
    return this._selectedProjectId;
  }

  getCurrentPollSeq() {
    return this._pollSeq;
  }

  // --- 唯一 ID / 幂等键生成器 ---

  generateRequestKey() {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
      return crypto.randomUUID();
    }
    return 'req_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 10);
  }

  // --- 基础请求工具 ---

  _getHeaders(includeProject = true, includeJson = false) {
    const headers = {};
    if (this._userToken) {
      headers['Authorization'] = `Bearer ${this._userToken}`;
    }
    if (includeProject && this._selectedProjectId) {
      headers['X-Hub-Project'] = this._selectedProjectId;
    }
    if (includeJson) {
      headers['Content-Type'] = 'application/json; charset=utf-8';
    }
    return headers;
  }

  _calculateByteLength(str) {
    if (typeof TextEncoder !== 'undefined') {
      return new TextEncoder().encode(str).length;
    }
    // Node.js Buffer fallback
    if (typeof Buffer !== 'undefined') {
      return Buffer.byteLength(str, 'utf8');
    }
    // UTF-8 byte length estimation fallback
    let s = str.length;
    for (let i = str.length - 1; i >= 0; i--) {
      const code = str.charCodeAt(i);
      if (code > 0x7f && code <= 0x7ff) s++;
      else if (code > 0x7ff && code <= 0xffff) s += 2;
      if (code >= 0xdc00 && code <= 0xdfff) i--; // surrogate pair
    }
    return s;
  }

  // --- 3 个白名单 HTTP 端点 ---

  /**
   * 检查服务与调度健康状态
   * GET /health
   */
  async getHealth() {
    const url = `${this.baseUrl}/health`;
    const response = await fetch(url, {
      method: 'GET',
      headers: this._getHeaders(false, false)
    });

    let data;
    try {
      data = await response.json();
    } catch (_) {
      throw new Error(`心跳接口返回格式异常: HTTP ${response.status}`);
    }

    if (!response.ok) {
      const msg = data && data.error ? data.error : `HTTP ${response.status} ${response.statusText}`;
      throw new Error(`服务心跳异常: ${msg}`);
    }

    return data; // { ok: boolean, supervisor: string, simulation: boolean }
  }

  /**
   * 获取工作台最新状态快照
   * GET /api/state
   * @param {Object} [meta]
   * @param {number} [meta.seq] - 期望的轮询序号，用于比对丢弃过期响应
   * @param {string} [meta.expectedProjectId] - 期望的项目 ID
   */
  async getState(meta = {}) {
    const expectedSeq = meta.seq !== undefined ? meta.seq : this._pollSeq;
    const expectedProject = meta.expectedProjectId !== undefined ? meta.expectedProjectId : this._selectedProjectId;

    const url = `${this.baseUrl}/api/state`;
    const response = await fetch(url, {
      method: 'GET',
      headers: this._getHeaders(true, false)
    });

    // 检查响应回来前是否发生过项目切换或新的拉取
    if (expectedSeq !== this._pollSeq || expectedProject !== this._selectedProjectId) {
      const discardErr = new Error('响应已过期（项目已切换或发生新请求），已丢弃');
      discardErr.name = 'StaleResponseError';
      discardErr.discarded = true;
      throw discardErr;
    }

    let data;
    try {
      data = await response.json();
    } catch (_) {
      throw new Error(`状态接口返回格式异常: HTTP ${response.status}`);
    }

    if (!response.ok) {
      const msg = data && data.error ? data.error : `HTTP ${response.status} ${response.statusText}`;
      throw new Error(`获取状态快照失败: ${msg}`);
    }

    return data;
  }

  /**
   * 提交动作
   * POST /api/action
   * @param {string} action - 动作名称
   * @param {Object} [args={}] - 参数字典
   */
  async postAction(action, args = {}) {
    if (!action || typeof action !== 'string') {
      throw new Error('动作名称必须为非空字符串');
    }

    // 严禁前端调用 Agent 内部私有工作流方法
    if (BLOCKED_INTERNAL_ACTIONS.has(action)) {
      throw new Error(`操作 "${action}" 为 Agent 内部调度工具，前端面板禁止直接调用`);
    }

    const payloadObj = {
      action,
      args: args || {}
    };

    const payloadJson = JSON.stringify(payloadObj);
    const byteLength = this._calculateByteLength(payloadJson);

    if (byteLength > MAX_PAYLOAD_BYTES) {
      throw new Error(
        `请求体体积 (${byteLength.toLocaleString()} 字节) 超过后端 262,144 字节上限，拒绝发送`
      );
    }

    const url = `${this.baseUrl}/api/action`;
    const response = await fetch(url, {
      method: 'POST',
      headers: this._getHeaders(true, true),
      body: payloadJson
    });

    let data;
    try {
      data = await response.json();
    } catch (_) {
      throw new Error(`动作接口返回非 JSON 数据: HTTP ${response.status}`);
    }

    // 先验 HTTP 状态码再解包 {error}
    if (!response.ok) {
      const errorMsg = data && data.error ? data.error : `HTTP ${response.status} ${response.statusText}`;
      const err = new Error(errorMsg);
      err.status = response.status;
      err.data = data;
      throw err;
    }

    // 成功时解包 {result: ...}
    return data ? data.result : null;
  }
}

// 导出为浏览器全局对象与 CommonJS / ES 模块
if (typeof window !== 'undefined') {
  window.HubApiClient = HubApiClient;
}
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { HubApiClient, MAX_PAYLOAD_BYTES, BLOCKED_INTERNAL_ACTIONS };
}
