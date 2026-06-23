"""
Reads voice_examples.txt, asks Claude for a tweet in that voice,
runs a tiny safety net, posts to X.

Run from GitHub Actions on a 4-6 hour schedule.
"""

import os
import random
import re
import sys

import anthropic
import tweepy


# --- 1. Config ----------------------------------------------------------------

# Pulled from GitHub Actions "secrets" (set in repo settings, not in code)
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
X_API_KEY = os.environ["X_API_KEY"]
X_API_SECRET = os.environ["X_API_SECRET"]
X_ACCESS_TOKEN = os.environ["X_ACCESS_TOKEN"]
X_ACCESS_TOKEN_SECRET = os.environ["X_ACCESS_TOKEN_SECRET"]

# A small list of words/phrases the bot should never post.
# Edit freely. Lowercase. Matched as substrings.
BANNED_WORDS = [
    # add your own, e.g.:
    # "rip", "rest in peace",   # avoid auto-condolences
    # "trump", "biden",         # avoid politics if you want
]

# How many of your real tweets to show Claude as voice examples each run
NUM_EXAMPLES_TO_SHOW = 40

# Max tweet length (X allows 280; we leave a little buffer)
MAX_TWEET_LEN = 270


# --- 2. Load voice examples ---------------------------------------------------

with open("voice_examples.txt", "r", encoding="utf-8") as f:
    all_examples = [line.strip() for line in f if line.strip()]

if len(all_examples) < 20:
    sys.exit("Need at least 20 voice examples in voice_examples.txt")

# Sample a fresh subset each run so the bot doesn't get stuck in a rut
examples = random.sample(all_examples, min(NUM_EXAMPLES_TO_SHOW, len(all_examples)))
examples_block = "\n".join(f"- {t}" for t in examples)


# --- 3. Ask Claude for a tweet ------------------------------------------------

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

system_prompt = f"""You write tweets in the exact voice of a specific person, based on real examples of their tweets.

Here are real tweets from this person. Study the voice carefully — vocabulary, sentence rhythm, punctuation habits, what they find interesting, how they open and close, whether they use hashtags or emojis, capitalization, level of formality:

{examples_block}

Write ONE new tweet in this same voice. Rules:
- Sound like the same person who wrote the examples above. Not "an AI version of them" — them.
- Pick your own topic. Anything that fits their interests and voice. Vary it from run to run.
- Do not copy or closely paraphrase any example tweet.
- Do not use hashtags or emojis unless the examples consistently do.
- No quotation marks around the tweet. No "Here's a tweet:" preamble. Output the tweet text only, nothing else.
- Under {MAX_TWEET_LEN} characters."""

response = client.messages.create(
    model="claude-opus-4-7",
    max_tokens=400,
    temperature=1.0,  # high so tweets vary across runs
    system=system_prompt,
    messages=[{"role": "user", "content": "Write the tweet now."}],
)

tweet = response.content[0].text.strip()

# Strip surrounding quotes if Claude added them despite instructions
tweet = tweet.strip('"').strip("'").strip()


# --- 4. Safety net ------------------------------------------------------------

def reject(reason):
    print(f"REJECTED: {reason}")
    print(f"Tweet was: {tweet}")
    sys.exit(0)  # exit cleanly so the workflow doesn't show as failed

if len(tweet) == 0:
    reject("empty tweet")

if len(tweet) > 280:
    reject(f"too long ({len(tweet)} chars)")

lowered = tweet.lower()
for word in BANNED_WORDS:
    if word.lower() in lowered:
        reject(f"contains banned word: {word}")

# Catch obvious "I am an AI" failure modes
ai_giveaways = ["as an ai", "i'm an ai", "i am an ai", "language model", "as a language"]
if any(p in lowered for p in ai_giveaways):
    reject("sounds like an AI disclaimer")

# Catch near-duplicates of the example set (the model copying a real tweet)
def normalize(s):
    return re.sub(r"[^a-z0-9 ]", "", s.lower())

norm_tweet = normalize(tweet)
for ex in all_examples:
    norm_ex = normalize(ex)
    # crude similarity: if tweet shares a long substring with any example
    if len(norm_tweet) > 30 and norm_tweet[:30] == norm_ex[:30]:
        reject(f"too similar to existing tweet: {ex}")


# --- 5. Post to X -------------------------------------------------------------

x_client = tweepy.Client(
    consumer_key=X_API_KEY,
    consumer_secret=X_API_SECRET,
    access_token=X_ACCESS_TOKEN,
    access_token_secret=X_ACCESS_TOKEN_SECRET,
)

result = x_client.create_tweet(text=tweet)
print(f"POSTED: {tweet}")
print(f"Tweet ID: {result.data['id']}")
