import json,os,subprocess,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from hub.vm_bridge import VmBridge

class Thumbnail(unittest.TestCase):
 def test_host_thumbnail_does_not_override_power_and_consumes_frame(self):
  with tempfile.TemporaryDirectory() as folder:
   b=VmBridge(folder);(b.root/'status.json').write_text(json.dumps({'updated':time.time(),'busy':'other-agent','protocol':4,'operations':['thumbnail']}),encoding='utf-8')
   with patch.object(b,'launch_helper'):
    queued=b.control('thumbnail',vm_name='Hub')
   self.assertFalse((b.root/'power-override.json').exists())
   ident=queued['request_id'];request=b.requests/(ident+'.json');result=b.results/(ident+'.json')
   self.assertEqual(json.loads(request.read_text())['vm_name'],'Hub')
   result.write_text(json.dumps({'state':'completed','available':True,'image_data':'frame'}),encoding='utf-8')
   self.assertEqual(b.control('result',request_id=ident)['image_data'],'frame')
   self.assertFalse(result.exists());self.assertFalse(request.exists())

 @unittest.skipUnless(os.name=='nt','PowerShell helper mock')
 def test_official_method_arguments_and_rgb565_payload(self):
  source=(Path(__file__).parents[1]/'tools/Start-HubVmBridge.ps1').read_text(encoding='utf-8-sig')
  body=source.split("} elseif ($job.action -eq 'thumbnail') {",1)[1].split("} elseif ($job.action -eq 'connect') {",1)[0]
  prefix=r"""
$ErrorActionPreference='Stop'
function Get-VM($Name){return @{Name=$Name;State='Running';Id=[guid]::Empty}}
function Get-CimInstance($Namespace,$ClassName,$Filter){if($Namespace -ne 'root\virtualization\v2'){throw 'Wrong WMI namespace'};return @{class=$ClassName}}
function Get-CimAssociatedInstance($InputObject,$Association,$ResultClassName){if($Association -ne 'Msvm_SettingsDefineState'){throw 'Wrong setting association'};return @{current=$true}}
function Invoke-CimMethod($InputObject,$MethodName,$Arguments){
 if($InputObject.class -ne 'Msvm_VirtualSystemManagementService' -or $MethodName -ne 'GetVirtualSystemThumbnailImage' -or -not $Arguments.TargetSystem.current -or $Arguments.WidthPixels -ne 320 -or $Arguments.HeightPixels -ne 180){throw 'Invalid official thumbnail arguments'}
 return @{ReturnValue=0;ImageData=[byte[]]::new(320*180*2)}
}
function Save-Json($path,$value){$value | ConvertTo-Json -Compress}
function Now{return 1}
$job=@{vm_name='Hub'};$resultPath='unused'
"""
  with tempfile.TemporaryDirectory() as folder:
   script=Path(folder)/'test.ps1';script.write_text(prefix+body,encoding='utf-8-sig')
   proc=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script)],capture_output=True,encoding='utf-8',errors='replace',timeout=15)
   self.assertEqual(proc.returncode,0,proc.stderr);frame=json.loads(proc.stdout.strip())
   self.assertEqual(frame['format'],'rgb565le');self.assertEqual(frame['width'],320);self.assertEqual(frame['height'],180);self.assertTrue(frame['available'])

 @unittest.skipUnless(os.name=='nt','PowerShell frame decoder')
 def test_cim_octetstring_header_and_raw_formats(self):
  source=(Path(__file__).parents[1]/'tools/Start-HubVmBridge.ps1').read_text(encoding='utf-8-sig')
  block=source.split('                        $expected=320*180*2',1)[1].split('                        Save-Json $resultPath',1)[0]
  scriptcode="""$ErrorActionPreference='Stop'
function Decode([byte[]]$pixels){
$expected=320*180*2
"""+block+"""
return ,$pixels
}
$raw=[byte[]]::new(115200);$raw[0]=248;$raw[1]=7
foreach($prefix in @([byte[]](0,1,194,0),[byte[]](0,1,194,4))){
 $frame=Decode ([byte[]]($prefix+$raw))
 if($frame.Length -ne 115200 -or $frame[0] -ne 248 -or $frame[1] -ne 7){throw 'OctetString pixels changed'}
}
if((Decode $raw).Length -ne 115200){throw 'raw frame rejected'}
$rejected=$false;try{Decode ([byte[]](@(0,0,0,1)+$raw))|Out-Null}catch{$rejected=$true}
if(-not $rejected){throw 'invalid header accepted'}
'PASS'
"""
  with tempfile.TemporaryDirectory() as folder:
   script=Path(folder)/'decode.ps1';script.write_text(scriptcode,encoding='utf-8-sig')
   result=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script)],capture_output=True,encoding='utf-8',errors='replace',timeout=15)
   self.assertEqual(result.returncode,0,result.stderr);self.assertIn('PASS',result.stdout)
