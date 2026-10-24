'use strict';
(() => {
  const H = window.HubDesktop;
  const { $, store, value, checked, number, text, bind, list, record } = H;
  bind('codexConfigForm','submit', async () => {
    await store.configureCodex({cwd:value('codexCwd'), permission:value('codexPermission'), max_runs:number('codexMaxRuns'), max_seconds:number('codexSeconds'), enabled:checked('codexEnabled'), confirmed:checked('codexConfigConfirm')});
    $('codexConfigConfirm').checked = false;
  });
  bind('codexTaskForm','submit', async () => {
    if (!checked('codexTaskConfirm')) throw new Error('请显式授权执行');
    await H.action('codex_submit',{agent:value('codexAgent'),prompt:value('codexInstruction'),confirmed:true}); $('codexTaskConfirm').checked = false;
  });
  bind('codexClear','click', () => { $('codexInstruction').value = ''; $('codexTaskConfirm').checked = false; });
  bind('openCodexIntegration','click', () => {
    if (!$('setupWizard').hidden) return;
    $('configModalToggle').checked = true;
    $('codexPanel').scrollIntoView?.({block:'start'});
  });
  H.render(v => {
    const d = v.rawSnapshot?.codex; if (!d) return;
    text('codexStatus',(d.config?.enabled ? '执行已启用' : '执行未启用') + ' · Hub remaining_runs ' + (d.remaining_runs ?? '未知'));
    list('codexRuns',(d.runs || []).map(r => record(r.id,r.result || r.prompt,r.status)));
    list('codexEvents',(d.events || []).map(e => H.longText(H.dump(e))));
  });
})();
