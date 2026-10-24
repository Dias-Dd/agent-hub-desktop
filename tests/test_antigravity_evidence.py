import json,tempfile,time,unittest
from datetime import datetime,timezone
from pathlib import Path
from hub.antigravity_evidence import historical_error_evidence

CID='b6f1259c-8576-47c8-a403-682596fd9715'
ERROR='Malformed function call: Function call is empty - no input to parse.'

class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'transcript.jsonl'
        self.now=time.time();self.sent='new message';self.answer='complete current answer'
        self.run={'thread_id':CID,'started':self.now,'finished':self.now+10}
        self.end={'conversation_id':CID,'status':'ERROR','error':ERROR,'response':self.answer}
        stamp=datetime.fromtimestamp(self.now,timezone.utc).isoformat()
        self.rows=[{'step_index':1,'type':'ERROR_MESSAGE','source':'SYSTEM','status':'DONE','content':ERROR},{'step_index':2,'type':'USER_INPUT','source':'USER_EXPLICIT','status':'DONE','created_at':stamp,'content':self.sent},{'step_index':3,'type':'PLANNER_RESPONSE','source':'MODEL','status':'DONE','content':self.answer}]
    def tearDown(self):self.temp.cleanup()
    def check(self,code=0):
        self.path.write_text(''.join(json.dumps(r)+'\n' for r in self.rows),encoding='utf-8')
        return historical_error_evidence(self.run,self.end,code,self.sent,self.path)
    def test_exact_historical_error_with_completed_current_turn(self):
        value=self.check();self.assertEqual(value['historical_error_step'],1);self.assertEqual(value['final_step'],3)
    def test_genuine_new_error_is_never_ignored_even_with_final_text(self):
        self.rows.insert(2,{'step_index':25,'type':'ERROR_MESSAGE','source':'SYSTEM','status':'DONE','content':ERROR})
        self.assertIsNone(self.check())
    def test_nonzero_exit_or_denied_action_is_not_promoted(self):
        self.assertIsNone(self.check(3));self.end['denied_actions']=[{'action':'mcp'}];self.assertIsNone(self.check())
    def test_partial_response_or_unfinished_step_is_not_promoted(self):
        self.end['response']='partial';self.assertIsNone(self.check());self.end['response']=self.answer
        self.rows[-1]['status']='ERROR';self.assertIsNone(self.check())
    def test_unmatched_input_old_timestamp_and_different_error_are_rejected(self):
        self.rows[1]['content']='another input';self.assertIsNone(self.check());self.rows[1]['content']=self.sent
        self.run['started']=self.now+50;self.assertIsNone(self.check());self.run['started']=self.now
        self.end['error']='different failure';self.assertIsNone(self.check())
    def test_missing_log_or_wrong_conversation_is_not_promoted(self):
        self.assertIsNone(historical_error_evidence(self.run,self.end,0,self.sent,self.path))
        self.end['conversation_id']='../not-a-conversation';self.assertIsNone(self.check())
    def test_cli_user_wrapper_and_later_turn_do_not_confuse_boundary(self):
        self.rows[1]['content']='<USER_REQUEST>\n'+self.sent+'\n</USER_REQUEST>\n<ADDITIONAL_METADATA>\nclock'
        self.rows.extend([{'step_index':4,'type':'USER_INPUT','content':'future message'},{'step_index':5,'type':'ERROR_MESSAGE','content':'future error'}])
        self.assertIsNotNone(self.check())
    def test_recovered_tool_read_error_is_reported_without_becoming_system_failure(self):
        self.rows.insert(2,{'step_index':25,'type':'GENERIC','source':'MODEL','status':'ERROR','content':'Encountered error in step execution: tool view_file: failed to read file: missing file'})
        evidence=self.check();self.assertEqual(evidence['handled_tool_error_steps'],[25])
        self.rows[2]['content']='Encountered error in step execution: '+ERROR
        self.assertIsNone(self.check())

    def test_stale_background_running_requires_matching_stream_completion(self):
        self.rows.insert(2,{'step_index':25,'type':'GENERIC','source':'MODEL','status':'RUNNING','content':'background command'})
        self.assertIsNone(self.check())
        evidence=historical_error_evidence(self.run,self.end,0,self.sent,self.path,completed_tool_steps={25})
        self.assertEqual(evidence['stream_confirmed_completed_steps'],[25])
        self.assertIsNone(historical_error_evidence(self.run,self.end,0,self.sent,self.path,completed_tool_steps={26}))
        self.rows[2]['type']='PLANNER_RESPONSE';self.path.write_text(''.join(json.dumps(r)+'\n' for r in self.rows),encoding='utf-8')
        self.assertIsNone(historical_error_evidence(self.run,self.end,0,self.sent,self.path,completed_tool_steps={25}))

    def test_duplicate_matching_input_in_same_time_range_is_ambiguous(self):
        self.rows.insert(2,dict(self.rows[1]));self.assertIsNone(self.check())

    def test_long_utf8_export_requires_complete_matching_stream(self):
        self.sent='request '+chr(0x4e2d)*2000
        self.answer='answer '+chr(0x6587)*5000
        self.end['response']=self.answer+'\n'
        def truncate(text):
            return text[:100]+'\n<truncated '+str(len(text[100:-100].encode('utf-8')))+' bytes>\n'+text[-100:]
        wrapped='<USER_REQUEST>\n'+self.sent+'\n</USER_REQUEST>\n<ADDITIONAL_METADATA>\nclock'
        self.rows[1].update(content=truncate(wrapped),truncated_fields=['content'])
        self.rows[-1].update(content=truncate(self.answer),truncated_fields=['content'])
        self.assertIsNone(self.check())
        def verify(responses):
            return historical_error_evidence(self.run,self.end,0,self.sent,self.path,completed_responses=responses)
        self.assertIsNotNone(verify({3:self.answer+'\n'}))
        self.assertIsNone(verify({3:self.answer[:-1]}))
        self.assertIsNone(verify({4:self.answer}))
        self.rows[-1]['truncated_fields']=[];self.check()
        self.assertIsNone(verify({3:self.answer}))
        self.rows[-1]['truncated_fields']=['content']
        self.rows[1]['content']=self.rows[1]['content'].replace('5700 bytes','5701 bytes')
        # A changed request must never match the exported anchor.
        self.sent+='changed';self.check()
        self.assertIsNone(verify({3:self.answer}))

if __name__=='__main__':unittest.main()
