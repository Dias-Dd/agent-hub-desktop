// Pi owns the agent loop. Hub owns authorization, tool effects and persistence.
import { Agent } from '@earendil-works/pi-agent-core';
import { streamSimple as completions } from '@earendil-works/pi-ai/api/openai-completions';
import { streamSimple as responses } from '@earendil-works/pi-ai/api/openai-responses';
import { streamSimple as anthropic } from '@earendil-works/pi-ai/api/anthropic-messages';
import { streamSimple as google } from '@earendil-works/pi-ai/api/google-generative-ai';
import { createInterface } from 'node:readline';
const output=value=>process.stdout.write(JSON.stringify(value)+'\n');
const pending=new Map();let counter=0,started=false;
function rpc(type,value){return new Promise((resolve,reject)=>{const id=String(++counter);pending.set(id,{resolve,reject});output({type,id,...value});});}
async function run(input){
 const streams={'openai-completions':completions,'openai-responses':responses,'anthropic-messages':anthropic,'google-generative-ai':google};
 const stream=streams[input.model.api];if(!stream)throw Error('Unsupported API protocol');
 const tools=input.tools.map(({function:f})=>({name:f.name,label:f.name,description:f.description,parameters:f.parameters,
  execute:async(id,args)=>{const result=await rpc('tool',{call_id:id,name:f.name,args});return {content:[{type:'text',text:JSON.stringify(result.value)}],details:{},isError:!!result.is_error,terminate:!!result.terminate};}}));
 const agent=new Agent({initialState:{model:input.model,systemPrompt:input.system,tools,messages:input.history},
  streamFn:(model,context,options)=>stream(model,context,{...options,apiKey:input.api_key,maxTokens:input.max_tokens,maxRetries:0,
   onPayload:async payload=>{await rpc('reserve',{payload});return payload;}}),
  toolExecution:'sequential',identity:{attribution:null}});
 agent.subscribe(async event=>{
  if(event.type==='message_update'&&event.assistantMessageEvent.type==='text_delta')output({type:'delta',text:event.assistantMessageEvent.delta});
  if(event.type==='message_end')await rpc('checkpoint',{history:agent.state.messages});
 });
 await agent.prompt(input.prompt);
 const messages=agent.state.messages;
 const last=[...messages].reverse().find(m=>m.role==='assistant');
 if(!last||['error','aborted'].includes(last.stopReason))throw Error(last?.errorMessage||'Pi did not complete');
 output({type:'result',text:last.content.filter(c=>c.type==='text').map(c=>c.text).join('\n'),history:messages,usage:last.usage});
}
const lines=createInterface({input:process.stdin,crlfDelay:Infinity});
lines.on('line',line=>{
 try{const value=JSON.parse(line);if(value.type==='reply'){const p=pending.get(value.id);if(p){pending.delete(value.id);value.error?p.reject(Error(value.error)):p.resolve(value);}}
 else if(value.type==='run'&&!started){started=true;run(value).then(()=>process.exit(0)).catch(error=>{output({type:'error',message:String(error.message)});process.exit(1);});}}
 catch{output({type:'error',message:'Invalid bridge protocol'});process.exit(1);}
});
lines.on('close',()=>process.exit(1));
