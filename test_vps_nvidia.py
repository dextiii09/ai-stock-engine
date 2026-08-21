import os, sys
from dotenv import load_dotenv
load_dotenv('/home/ubuntu/ai_stock/.env')
sys.path.insert(0, '/home/ubuntu/ai_stock/backend')
from agents.gemini_agent import NvidiaMacroAgent
agent = NvidiaMacroAgent()
print('Candidates:', agent._model_candidates)
try:
    res = agent._call_nvidia('Hello! Say hi in 5 words.')
    print('SUCCESS:', res)
except Exception as e:
    print('ERROR:', type(e), e)
