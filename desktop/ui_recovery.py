"""Bounded UI-only recovery; never modifies Hub jobs or model sessions."""
class RecoveryPolicy:
    def __init__(self):
        self.attempts=[];self.blank_count=0
    def allow(self,now,manual=False):
        self.attempts=[t for t in self.attempts if now-t<300]
        if manual:self.attempts=[]
        if self.attempts and now-self.attempts[-1]<15:return False
        if len(self.attempts)>=3:return False
        self.attempts.append(now);self.blank_count=0;return True
    def observe(self,has_ui):
        self.blank_count=0 if has_ui else self.blank_count+1
        return self.blank_count>=2
