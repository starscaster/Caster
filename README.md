# Caster
DeepSeek API Proxy
Fix DeepSeek V4's new API (thinking mode / reasoning_effort) not working with chatbox UIs like SillyTavern, OpenCode, etc.

How to Use
1. Install

BASH
pip install flask requests
2. Set your DeepSeek key

BASH
export DEEPSEEK_KEY="sk-your-key-here"
3. Run

BASH
python proxy.py
4. In your chatbox

Set the API endpoint to:

TEXT
http://localhost:20123/v1/chat/completions

deepseek-v4-flash-thinking → Flash + hight thinking

deepseek-v4-flash-max → Flash + max thinking

deepseek-v4-pro-thinking → Pro + hight thinking

deepseek-v4-pro-max → Pro + max thinking
