# Caster
DeepSeek API Proxy
Fix DeepSeek V4's new API (thinking mode / reasoning_effort / reasoning_content) not working with Chatbox

How to Use
1. Install

pip install flask requests


2. Set your DeepSeek key

export DEEPSEEK_KEY="sk-your-key-here"

(You can also set the API key on the client side, and the proxy will apply the passed value)


3. Run

python proxy.py


4. In your chatbox

Set the API endpoint to:
http://localhost:20123/v1/chat/completions

deepseek-v4-flash-thinking → Flash + hight thinking

deepseek-v4-flash-max → Flash + max thinking

deepseek-v4-pro-thinking → Pro + hight thinking

deepseek-v4-pro-max → Pro + max thinking
