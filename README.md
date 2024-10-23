# chatbot_2


Instructions for Mac:
Get an anthropic api key (or use another LLM) and set as env variable:
export ANTHROPIC_API_KEY='key'


(replace jamesRNA with name for your venv)
conda create -n jamesRNA python=3.9
conda activate jamesRNA


pip install requests anthropic typing selenium webdriver_manager


Testing:
Navigate to the root directory of this project and run chatbot.py

In-progress:
API to communicate with front end (routes.py, app.py are not set up with the new chatbot.py)
