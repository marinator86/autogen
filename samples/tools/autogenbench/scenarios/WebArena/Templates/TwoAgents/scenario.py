import os
import json
import testbed_utils
import autogen
import evaluation_harness
import re
from autogen.agentchat.contrib.multimodal_web_surfer import MultimodalWebSurferAgent
from autogen.runtime_logging import logging_enabled, log_event
from mmagent import MultimodalAgent

from evaluation_harness.env_config import ACCOUNTS, GITLAB, MAP, REDDIT, SHOPPING, SHOPPING_ADMIN, WIKIPEDIA, HOMEPAGE

testbed_utils.init()
##############################

REPLACEMENTS = {
    "__REDDIT__": REDDIT,
    "__SHOPPING__": SHOPPING,
    "__SHOPPING_ADMIN__": SHOPPING_ADMIN,
    "__GITLAB__": GITLAB,
    "__WIKIPEDIA__": WIKIPEDIA,
    "__MAP__": MAP,
    "__HOMEPAGE__": HOMEPAGE,
}

# Expand the prompt and the full task
task_prompt = ""
TASK = None
with open("task_prompt.json.txt", "rt") as fh:
    task_prompt = fh.read()
with open("task_prompt.json", "wt") as fh:
    for k in REPLACEMENTS:
        task_prompt = task_prompt.replace(k, REPLACEMENTS[k])
    fh.write(task_prompt)
    TASK = json.loads(task_prompt)

full_task = ""
with open("full_task.json.txt", "rt") as fh:
    full_task = fh.read()
with open("full_task.json", "wt") as fh:
    for k in REPLACEMENTS:
        full_task = full_task.replace(k, REPLACEMENTS[k])
    fh.write(full_task)

# Load the LLM config list
config_list = autogen.config_list_from_json("OAI_CONFIG_LIST")
llm_config = testbed_utils.default_llm_config(config_list, timeout=300)

if logging_enabled():
    log_event(os.path.basename(__file__), name="LoadedConfigLists")

web_surfer = MultimodalWebSurferAgent(
    "web_surfer",
    llm_config=llm_config,
    is_termination_msg=lambda x: str(x).find("TERMINATE") >= 0 or str(x).find("FINAL ANSWER") >= 0,
    human_input_mode="NEVER",
    headless=True,
    chromium_channel="chromium",
    chromium_data_dir=None,
    start_page=HOMEPAGE,
    debug_dir=os.getenv("WEB_SURFER_DEBUG_DIR", None),
)

user_proxy = MultimodalAgent(
    "user_proxy",
    system_message="""You are a general-purpose AI assistant and can handle many questions -- but you don't have access to a web browser. However, the user you are talking to does have a browser, and you can see the screen. Provide short direct instructions to them to take you where you need to go to answer the initial question posed to you.

Once the user has taken the final necessary action to complete the task, and you have fully addressed the initial request, reply with the word TERMINATE.""",
    llm_config=llm_config,
    human_input_mode="NEVER",
    is_termination_msg=lambda x: False,
    max_consecutive_auto_reply=20,
)

# Login to the necessary websites
if "reddit" in TASK["sites"]:
    if logging_enabled():
        log_event(os.path.basename(__file__), name="start_reddit_task")
    login_url = REDDIT
    username = ACCOUNTS["reddit"]["username"]
    password = ACCOUNTS["reddit"]["password"]
    try:
        user_proxy.initiate_chat(
            web_surfer,
            message=f"Navigate to {login_url}. Click \"Log in\", type the username '{username}', and password is '{password}'. Finally click the login button.",
            clear_history=True,
        )
    except Exception as e:
        import traceback
        if logging_enabled():
            exc_type = type(e).__name__
            exc_message = str(e)
            exc_traceback = traceback.format_exc().splitlines()
            log_event(os.path.basename(__file__), name="exception_thrown", exc_type=exc_type, exc_message=exc_message, exc_traceback=exc_traceback)

        raise e
    user_proxy.reset()
    web_surfer.reset()


if "gitlab" in TASK["sites"]:
    if logging_enabled():
        log_event(os.path.basename(__file__), name="start_gitlab_task")
    login_url = GITLAB
    username = ACCOUNTS["gitlab"]["username"]
    password = ACCOUNTS["gitlab"]["password"]
    user_proxy.initiate_chat(
        web_surfer,
        message=f"Navigate to {login_url}. type the username '{username}', and password is '{password}'. Finally click the 'Sign in' button.",
        clear_history=True,
    )
    user_proxy.reset()
    web_surfer.reset()

# TODO: Add the shopping sites


# Navigate to the starting url
if logging_enabled():
    log_event(os.path.basename(__file__), name="navigate_start_url")
start_url = TASK["start_url"]
if start_url == REDDIT:
    start_url = start_url + "/forums"
user_proxy.send(f"Navigate to {start_url}", web_surfer, request_reply=True)

user_proxy.reset()
web_surfer.reset()

print("MAIN TASK STARTING !#!#")

# Provide some background about the pages
site_description_prompt = ""
if start_url.startswith(REDDIT):
    site_description_prompt = ", which is a Postmill forum populated with a large sample of data crawled from Reddit. Postmill is similar to Reddit, but the UI is distinct, and 'subreddits' begin with /f/ rather than /r/"
elif start_url.startswith(GITLAB):
    site_description_prompt = ", which is a Gitlab site populated with various programming projects. Gitlab is similar to GitHub, though the UIs are slightly different"

if logging_enabled():
    log_event(os.path.basename(__file__), name="main_task_initiate_chat")

try:
    web_surfer.initiate_chat(
        user_proxy,
        message=f"""
We are visiting the website {start_url}{site_description_prompt}. On this website, please complete the following task:

    {TASK['intent']}
""".strip(),
        clear_history=True,
    )
except Exception as e:
    import traceback
    if logging_enabled():
        exc_type = type(e).__name__
        exc_message = str(e)
        exc_traceback = traceback.format_exc().splitlines()
        log_event(os.path.basename(__file__), name="exception_thrown", exc_type=exc_type, exc_message=exc_message, exc_traceback=exc_traceback)

    raise e

# Extract a final answer
#########################
if logging_enabled():
    log_event(os.path.basename(__file__), name="extract_final_answer")
web_surfer.send(
    f"""Read the above conversation and output a FINAL ANSWER to the original request. The original request is repeated here for convenience:

{TASK['intent']}

To output the final answer, use the following template: FINAL ANSWER: [YOUR FINAL ANSWER]
Your FINAL ANSWER should be as few words as possible
If the original request was not a question, or you did not find a definitive answer, simply summarize the final state of the page or task as your FINAL ANSWER.""",
    user_proxy,
    request_reply=False,
    silent=True,
)
final_answer = user_proxy.generate_reply(sender=web_surfer)

m = re.search("FINAL ANSWER:(.*)$", final_answer, re.DOTALL)
if m:
    final_answer = m.group(1).strip()

if logging_enabled():
    log_event(os.path.basename(__file__), name="final_answer", final_answer=final_answer)

print('page.stop("' + final_answer + '")')
print("MAIN TASK COMPLETE !#!#")

########## EVALUATION ##########

# playwright = web_surfer._playwright
context = web_surfer._context
page = web_surfer._page
cdp_session = context.new_cdp_session(page)
config_file = "full_task.json"

evaluator = evaluation_harness.evaluator_router(config_file)
score = evaluator(
    trajectory=evaluation_harness.make_answer_trajecotry(final_answer),
    config_file=config_file,
    page=page,
    client=cdp_session,
)

if logging_enabled():
    log_event(os.path.basename(__file__), name="final_score", final_score=str(score))
print("FINAL SCORE: " + str(score))

################################
testbed_utils.finalize(agents=[web_surfer, user_proxy])
