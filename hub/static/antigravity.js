'use strict';
(() => {
  const H = window.HubDesktop;
  const { $, store, value, checked, number, text, bind, list, record } = H;
  bind('antigravityConfigForm','submit', async () => {
    await store.configureAntigravity({cwd:value('antigravityCwd'),permission:value('antigravityPermission'),max_runs:number('antigravityMaxRuns'),max_seconds:number('antigravitySeconds'),enabled:checked('antigravityEnabled'),confirmed:checked('antigravityConfigConfirm')});
    $('antigravityConfigConfirm').checked = false;
  });
  bind('refreshAntigravityConfig','click', async () => { await store.refreshAntigravityQuota(); text('antigravityValidation','官方额度已更新'); });
  bind('antigravityTaskForm','submit', async () => {
    if (!checked('antigravityTaskConfirm')) throw new Error('请显式授权执行');
    await H.action('antigravity_submit',{agent:value('antigravityAgent'),prompt:value('antigravityInstruction'),confirmed:true}); $('antigravityTaskConfirm').checked = false;
  });
  bind('antigravityClear','click', () => { $('antigravityInstruction').value = ''; $('antigravityTaskConfirm').checked = false; });
  bind('openAntigravityIntegration','click', () => {
    if (!$('setupWizard').hidden) return;
    $('configModalToggle').checked = true;
    $('antigravityPanel').scrollIntoView?.({block:'start'});
  });
  H.render(v => {
    const d = v.rawSnapshot?.antigravity; if (!d) return;
    text('antigravityStatus',(d.config?.enabled ? '执行已启用' : '执行未启用') + ' · Hub remaining_runs ' + (d.remaining_runs ?? '未知'));
    text('antigravityQuota',v.agents.filter(a => a.provider === 'antigravity').map(a => a.id + ': ' + H.dump(a.sharedQuota.windows)).join('\n'));
    list('antigravityRuns',(d.runs || []).map(r => record(r.id,r.result || r.prompt,r.status)));
    list('antigravityEvents',(d.events || []).map(e => H.longText(H.dump(e))));
  });
})();
