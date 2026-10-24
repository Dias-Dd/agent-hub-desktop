"use strict";
(() => {
 const H=window.HubDesktop;
 function open(){document.getElementById('openIntegrations').click();}
 H.openProviderGuide=open;
 for(const id of ['reopenSetup','openProviderGuide','openDeepSeekIntegration'])H.bind(id,'click',open,false);
 for(const id of ['setupNext','setupClose'])H.bind(id,'click',()=>{H.$('setupWizard').hidden=true;},false);
 H.bind('setupBack','click',()=>{},false);
})();
