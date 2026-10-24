'use strict';
(() => {const id=new URLSearchParams(location.hash.slice(1)).get('id');if(!window.opener?.HubWindows){document.body.textContent='工作台连接已关闭，请重新打开此窗口。';return;}window.opener.HubWindows.attach(window,id);})();
