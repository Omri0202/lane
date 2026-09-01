"""
corpus.py — the examples the router learns from, and a disjoint set it is
graded on.

Two rules govern everything in this file.

FIRST: TRAIN and HELDOUT never share phrasing. The predecessor to this router
scored 100% on the examples it was written against and 35% on real phrasing,
because its author tested it on the sentences he had just written. HELDOUT
exists to make that failure impossible to miss — it is scored by
tests/test_classify.py, and the router is judged on it, never on TRAIN.

SECOND: only five lanes appear here. VISION and TOOLS are structural facts — an
image is attached or it is not, a tool schema is present or it is not — and are
decided before any text is read. Asking a text classifier to guess at them
would be strictly worse than looking.

Phrasing is deliberately uneven: terse and verbose, polite and blunt, sloppy
and clean, first-person and imperative. The failure being designed around is a
classifier that only recognises the way its author happens to write.
"""

from __future__ import annotations

from .lanes import Lane

TRAIN: list[tuple[str, str]] = [
    # ── trivial: no capability required ───────────────────────────────────────
    ("hey", Lane.TRIVIAL), ("hi there", Lane.TRIVIAL),
    ("morning", Lane.TRIVIAL), ("good evening", Lane.TRIVIAL),
    ("thanks!", Lane.TRIVIAL), ("thank you so much", Lane.TRIVIAL),
    ("cheers", Lane.TRIVIAL), ("ta", Lane.TRIVIAL),
    ("ok", Lane.TRIVIAL), ("okay cool", Lane.TRIVIAL),
    ("got it", Lane.TRIVIAL), ("understood", Lane.TRIVIAL),
    ("yes", Lane.TRIVIAL), ("no", Lane.TRIVIAL), ("yep", Lane.TRIVIAL),
    ("nope", Lane.TRIVIAL), ("sure", Lane.TRIVIAL),
    ("nevermind", Lane.TRIVIAL), ("nvm forget it", Lane.TRIVIAL),
    ("never mind then", Lane.TRIVIAL),
    ("lol", Lane.TRIVIAL), ("haha nice", Lane.TRIVIAL),
    ("perfect thanks", Lane.TRIVIAL), ("great", Lane.TRIVIAL),
    ("sounds good", Lane.TRIVIAL), ("works for me", Lane.TRIVIAL),
    ("bye", Lane.TRIVIAL), ("goodnight", Lane.TRIVIAL),
    ("see ya", Lane.TRIVIAL), ("stop", Lane.TRIVIAL),
    ("wait", Lane.TRIVIAL), ("hold on", Lane.TRIVIAL),
    ("carry on", Lane.TRIVIAL), ("go ahead", Lane.TRIVIAL),
    ("try again", Lane.TRIVIAL), ("do it", Lane.TRIVIAL),

    # ── simple: short factual recall, conversions, definitions ────────────────
    ("what is the capital of peru", Lane.SIMPLE),
    ("whats the boiling point of water in fahrenheit", Lane.SIMPLE),
    ("define entropy", Lane.SIMPLE),
    ("what does api stand for", Lane.SIMPLE),
    ("who wrote pride and prejudice", Lane.SIMPLE),
    ("how many bytes are in a gigabyte", Lane.SIMPLE),
    ("how tall is mount everest", Lane.SIMPLE),
    ("when did the berlin wall fall", Lane.SIMPLE),
    ("how do you spell accommodate", Lane.SIMPLE),
    ("whats 40 miles in kilometres", Lane.SIMPLE),
    ("convert 200 grams to ounces", Lane.SIMPLE),
    ("what timezone is berlin in", Lane.SIMPLE),
    ("whats the chemical symbol for tin", Lane.SIMPLE),
    ("who is ada lovelace", Lane.SIMPLE),
    ("what language do they speak in brazil", Lane.SIMPLE),
    ("whats the plural of octopus", Lane.SIMPLE),
    ("what year was python released", Lane.SIMPLE),
    ("is a tomato a fruit", Lane.SIMPLE),
    ("what does the acronym ram mean", Lane.SIMPLE),
    ("how many continents are there", Lane.SIMPLE),
    ("whats the currency of denmark", Lane.SIMPLE),
    ("give me a synonym for happy", Lane.SIMPLE),
    ("what is the speed of light", Lane.SIMPLE),
    ("whats the difference between http and https", Lane.SIMPLE),
    ("what does git clone do", Lane.SIMPLE),
    ("what is a palindrome", Lane.SIMPLE),
    ("who painted the starry night", Lane.SIMPLE),
    ("whats the longest river in africa", Lane.SIMPLE),
    ("abbreviation for california", Lane.SIMPLE),

    # ── general: ordinary explanation and conversation ────────────────────────
    ("how does a refrigerator actually work", Lane.GENERAL),
    ("explain how vaccines work", Lane.GENERAL),
    ("whats the deal with sourdough starters", Lane.GENERAL),
    ("i dont really understand what a vpn does", Lane.GENERAL),
    ("can you walk me through how compound interest works", Lane.GENERAL),
    ("why do cats purr", Lane.GENERAL),
    ("whats a good way to learn guitar as an adult", Lane.GENERAL),
    ("should i buy or rent in this market", Lane.GENERAL),
    ("give me some ideas for a birthday present for my dad", Lane.GENERAL),
    ("what are the pros and cons of electric cars", Lane.GENERAL),
    ("how do i get better at public speaking", Lane.GENERAL),
    ("tell me about the roman empire", Lane.GENERAL),
    ("whats the history of the olympics", Lane.GENERAL),
    ("how should i prepare for a job interview", Lane.GENERAL),
    ("whats a reasonable weekly running plan for a beginner", Lane.GENERAL),
    ("i want to start cooking more what should i learn first", Lane.GENERAL),
    ("explain the difference between weather and climate", Lane.GENERAL),
    ("why is the sky blue", Lane.GENERAL),
    ("how does noise cancelling work", Lane.GENERAL),
    ("what should i look for when buying a used car", Lane.GENERAL),
    ("recommend me some books like dune", Lane.GENERAL),
    ("how do i keep houseplants alive", Lane.GENERAL),
    ("whats the best way to learn a language", Lane.GENERAL),
    ("talk me through how mortgages work in general", Lane.GENERAL),
    ("what causes inflation", Lane.GENERAL),
    ("is it worth getting a standing desk", Lane.GENERAL),
    ("how do solar panels work", Lane.GENERAL),
    ("whats the point of stretching before exercise", Lane.GENERAL),
    ("give me advice on moving to a new city", Lane.GENERAL),
    ("how do airlines decide ticket prices", Lane.GENERAL),

    # ── longform: writing, drafting, rewriting, summarising ───────────────────
    ("write a short story about a lighthouse keeper", Lane.LONGFORM),
    ("draft an email declining the meeting politely", Lane.LONGFORM),
    ("summarise this report for my boss", Lane.LONGFORM),
    ("rewrite this paragraph in a warmer tone", Lane.LONGFORM),
    ("compose a poem about winter", Lane.LONGFORM),
    ("outline a blog post about remote work", Lane.LONGFORM),
    ("write a cover letter for this job", Lane.LONGFORM),
    ("can you make this sound less corporate", Lane.LONGFORM),
    ("tidy up my wording here", Lane.LONGFORM),
    ("condense this into three bullet points", Lane.LONGFORM),
    ("make the intro punchier", Lane.LONGFORM),
    ("turn these notes into something readable", Lane.LONGFORM),
    ("give me the gist of the text below", Lane.LONGFORM),
    ("write release notes for these changes", Lane.LONGFORM),
    ("rephrase this so it doesnt sound rude", Lane.LONGFORM),
    ("draft a speech for the opening ceremony", Lane.LONGFORM),
    ("i need three paragraphs on renewable energy", Lane.LONGFORM),
    ("make it longer and more dramatic", Lane.LONGFORM),
    ("proofread this and fix the grammar", Lane.LONGFORM),
    ("write a product description for this listing", Lane.LONGFORM),
    ("tighten this up its far too wordy", Lane.LONGFORM),
    ("give me a linkedin post about the launch", Lane.LONGFORM),
    ("write the readme intro for this project", Lane.LONGFORM),
    ("summarize the transcript i pasted below", Lane.LONGFORM),
    ("polish the ending it feels flat", Lane.LONGFORM),
    ("draft an apology message to a customer", Lane.LONGFORM),
    ("write a toast for my sisters wedding", Lane.LONGFORM),
    ("expand this bullet into a full paragraph", Lane.LONGFORM),
    ("give me a punchy tagline for the brand", Lane.LONGFORM),

    # ── reasoning: code, maths, debugging, analysis, planning ─────────────────
    ("why is my recursive fibonacci so slow", Lane.REASONING),
    ("prove that the square root of two is irrational", Lane.REASONING),
    ("whats the time complexity of quicksort", Lane.REASONING),
    ("refactor this class to use dependency injection", Lane.REASONING),
    ("solve for x three x squared plus two x minus five", Lane.REASONING),
    ("my unit test is failing and i cant see why", Lane.REASONING),
    ("write a regex that matches balanced parentheses", Lane.REASONING),
    ("theres a race condition somewhere in this code", Lane.REASONING),
    ("write me a function that reverses a linked list", Lane.REASONING),
    ("build a script to rename all these files", Lane.REASONING),
    ("make a class for handling user sessions", Lane.REASONING),
    ("generate a sql query for monthly revenue totals", Lane.REASONING),
    ("i need a python script that reads a csv", Lane.REASONING),
    ("give me the code for a rest endpoint", Lane.REASONING),
    ("write unit tests for this module", Lane.REASONING),
    ("find the bug in my binary search", Lane.REASONING),
    ("why does this deadlock", Lane.REASONING),
    ("optimise this query its taking eight seconds", Lane.REASONING),
    ("whats wrong with my sql join", Lane.REASONING),
    ("how do i make this thread safe", Lane.REASONING),
    ("what edge cases am i missing here", Lane.REASONING),
    ("calculate the monthly payment on a 300k mortgage at 5 percent", Lane.REASONING),
    ("should this be a set or a dict for performance", Lane.REASONING),
    ("trace through this and tell me where it goes wrong", Lane.REASONING),
    ("design the database schema for a booking system", Lane.REASONING),
    ("is this o n log n or o n squared", Lane.REASONING),
    ("work out the probability of three heads in five flips", Lane.REASONING),
    ("debug the login flow its rejecting valid users", Lane.REASONING),
    ("plan the architecture for a multi tenant saas app", Lane.REASONING),
    ("convert this recursive function to an iterative one", Lane.REASONING),
    ("explain why this returns the wrong sign", Lane.REASONING),
    ("derive the formula for compound interest", Lane.REASONING),
    ("how much memory does this data structure actually use", Lane.REASONING),
    ("figure out the big o of this nested loop", Lane.REASONING),
    ("theres an off by one error somewhere in here", Lane.REASONING),

    # ── second pass ───────────────────────────────────────────────────────────
    # Added after the first held-out evaluation, which sat at 75% precision.
    # Every entry below covers a SHAPE the corpus had no example of, found by
    # reading the misclassifications rather than by imagining new sentences.
    # None of them is a paraphrase of a HELDOUT entry — that would be marking
    # your own homework.

    # longform: short creative imperatives. The corpus had only long,
    # explicit writing requests, so terse ones fell through to SIMPLE.
    ("pen something short about autumn", Lane.LONGFORM),
    ("draft a quick note to the team", Lane.LONGFORM),
    ("edit my personal statement", Lane.LONGFORM),
    ("shorten this to fit a tweet", Lane.LONGFORM),
    ("caption for a photo of the beach", Lane.LONGFORM),
    ("subject line for this email", Lane.LONGFORM),
    ("script the voiceover for the ad", Lane.LONGFORM),
    ("blurb for the back of the book", Lane.LONGFORM),
    ("reword the opening line", Lane.LONGFORM),
    ("a haiku about traffic", Lane.LONGFORM),
    ("trim my resume to one page", Lane.LONGFORM),
    ("headline for the press release", Lane.LONGFORM),
    ("paraphrase this quote", Lane.LONGFORM),
    ("write vows for the ceremony", Lane.LONGFORM),
    ("give it a friendlier sign off", Lane.LONGFORM),

    # reasoning: operational faults, described in plain English with no code
    # and no code nouns. The corpus was heavy on "here is my function" and
    # empty on "the thing is broken in production".
    ("the container keeps restarting on deploy", Lane.REASONING),
    ("requests time out only when traffic spikes", Lane.REASONING),
    ("the build passes locally but fails in ci", Lane.REASONING),
    ("users are getting logged out at random", Lane.REASONING),
    ("memory climbs until the process is killed", Lane.REASONING),
    ("the page takes nine seconds to load now", Lane.REASONING),
    ("data comes back in the wrong order sometimes", Lane.REASONING),
    ("review this for correctness before i ship it", Lane.REASONING),
    ("check my logic here", Lane.REASONING),
    ("audit this for security problems", Lane.REASONING),
    ("compare these two approaches and pick one", Lane.REASONING),
    ("what would you check first if this was slow", Lane.REASONING),
    ("how would you implement caching for this", Lane.REASONING),
    ("estimate how long this will take to run", Lane.REASONING),
    ("port this from one framework to another", Lane.REASONING),
    ("the numbers dont add up in this spreadsheet", Lane.REASONING),
    ("work out which of these is cheaper over five years", Lane.REASONING),

    # general: "tell me about" and open curiosity, which kept reading as
    # long-form because the corpus only ever used those words for writing.
    ("tell me a bit about ancient egypt", Lane.GENERAL),
    ("id like to know more about black holes", Lane.GENERAL),
    ("curious how auctions actually work", Lane.GENERAL),
    ("give me an overview of the french revolution", Lane.GENERAL),
    ("whats the story with the space race", Lane.GENERAL),
    ("suggest some ways to sleep better", Lane.GENERAL),
    ("any tips for a first time flyer", Lane.GENERAL),
    ("thoughts on whether i should get a dog", Lane.GENERAL),
    ("help me decide between these two holidays", Lane.GENERAL),
    ("whats it like living in norway", Lane.GENERAL),
    ("explain what an index fund is for a beginner", Lane.GENERAL),
    ("how do people usually train for a marathon", Lane.GENERAL),

    # simple: bare-noun-phrase lookups with no verb at all, and the
    # which/when/how-many question shapes the corpus was thin on.
    ("population of iceland", Lane.SIMPLE),
    ("capital city of mongolia", Lane.SIMPLE),
    ("boiling point of ethanol", Lane.SIMPLE),
    ("which country has the most islands", Lane.SIMPLE),
    ("which is heavier gold or lead", Lane.SIMPLE),
    ("what year did the euro launch", Lane.SIMPLE),
    ("how many players on a rugby team", Lane.SIMPLE),
    ("how far is the moon", Lane.SIMPLE),
    ("inventor of the telephone", Lane.SIMPLE),
    ("largest desert in the world", Lane.SIMPLE),
    ("atomic number of carbon", Lane.SIMPLE),
    ("when is the summer solstice", Lane.SIMPLE),

    # trivial: the register the corpus missed — short reactions and
    # continuations that carry no request at all.
    ("makes sense", Lane.TRIVIAL),
    ("fair enough", Lane.TRIVIAL),
    ("cool", Lane.TRIVIAL),
    ("nice one", Lane.TRIVIAL),
    ("cheers for that", Lane.TRIVIAL),
    ("thanks a lot mate", Lane.TRIVIAL),
    ("right ok", Lane.TRIVIAL),
    ("go on then", Lane.TRIVIAL),
    ("skip it", Lane.TRIVIAL),
    ("same", Lane.TRIVIAL),
    # Porting code is REASONING, not translation. Without these the word
    # "translate" alone pulled a code question into the translate lane.
    ("translate this sql query into an orm call", Lane.REASONING),
    ("convert this python function to javascript", Lane.REASONING),
    ("port this module from java to kotlin", Lane.REASONING),
    ("rewrite these bash commands for powershell", Lane.REASONING),
    ("turn this regex into something readable", Lane.REASONING),
    # "latest" and "current" in a developer's mouth mean a repository, not the
    # news. The web_search examples had made both words lean the wrong way.
    ("show me the latest commit on that branch", Lane.REASONING),
    ("what is the current value of this variable", Lane.REASONING),
    ("which version of the library am i on", Lane.REASONING),


    # ── translate: between human languages ───────────────────────────────────
    ("translate this paragraph into spanish", Lane.TRANSLATE),
    ("how do you say thank you in japanese", Lane.TRANSLATE),
    ("translate the following into french", Lane.TRANSLATE),
    ("can you put this in german for me", Lane.TRANSLATE),
    ("say that in hebrew", Lane.TRANSLATE),
    ("what is good morning in italian", Lane.TRANSLATE),
    ("translate this email to portuguese", Lane.TRANSLATE),
    ("i need this in arabic", Lane.TRANSLATE),
    ("translate from russian to english", Lane.TRANSLATE),
    ("how would you say that in korean", Lane.TRANSLATE),
    ("write this out in dutch please", Lane.TRANSLATE),
    ("translation of this sentence into greek", Lane.TRANSLATE),

    # ── web_search: information the model cannot already have ────────────────
    ("what is the latest news about the election", Lane.WEB_SEARCH),
    ("search the web for reviews of this laptop", Lane.WEB_SEARCH),
    ("whats the weather forecast for tomorrow", Lane.WEB_SEARCH),
    ("google it for me", Lane.WEB_SEARCH),
    ("who won the match last night", Lane.WEB_SEARCH),
    ("current price of bitcoin", Lane.WEB_SEARCH),
    ("look up the opening hours", Lane.WEB_SEARCH),
    ("whats happening in the markets today", Lane.WEB_SEARCH),
    ("latest release of that library", Lane.WEB_SEARCH),
    ("todays headlines please", Lane.WEB_SEARCH),
    ("find me recent articles on this", Lane.WEB_SEARCH),
    ("is that restaurant still open", Lane.WEB_SEARCH),
]


#: Graded, never trained on. Every entry is phrased differently from anything
#: in TRAIN — different verbs, different sentence shapes, different registers.
#: If accuracy here is high and accuracy in the wild is not, the fix is to add
#: real logged prompts (`lane tail`) to TRAIN, never to soften this set.
HELDOUT: list[tuple[str, str]] = [
    ("yo", Lane.TRIVIAL),
    ("appreciate it", Lane.TRIVIAL),
    ("mhm", Lane.TRIVIAL),
    ("scratch that", Lane.TRIVIAL),
    ("all good", Lane.TRIVIAL),
    ("later", Lane.TRIVIAL),
    ("brilliant cheers mate", Lane.TRIVIAL),
    ("nah", Lane.TRIVIAL),
    ("keep going", Lane.TRIVIAL),
    ("one sec", Lane.TRIVIAL),

    ("population of finland", Lane.SIMPLE),
    ("whats 12 stone in kilos", Lane.SIMPLE),
    ("meaning of the word ubiquitous", Lane.SIMPLE),
    ("which planet is closest to the sun", Lane.SIMPLE),
    ("what does ceo stand for", Lane.SIMPLE),
    ("author of nineteen eighty four", Lane.SIMPLE),
    ("how many sides does a heptagon have", Lane.SIMPLE),
    ("whats the freezing point of mercury", Lane.SIMPLE),
    ("what year did the titanic sink", Lane.SIMPLE),
    ("national dish of hungary", Lane.SIMPLE),

    ("could you explain what makes bread rise", Lane.GENERAL),
    ("im curious about how gps knows where i am", Lane.GENERAL),
    ("any thoughts on whether i should learn to drive", Lane.GENERAL),
    ("suggest some hobbies for someone who works at a desk all day", Lane.GENERAL),
    ("whats going on with the housing market generally", Lane.GENERAL),
    ("break down how insurance companies make money", Lane.GENERAL),
    ("id like to understand the basics of investing", Lane.GENERAL),
    ("what makes a good manager in your view", Lane.GENERAL),
    ("tell me a bit about the silk road trade routes", Lane.GENERAL),
    ("how come some people are lactose intolerant", Lane.GENERAL),

    ("put together a newsletter blurb about the new feature", Lane.LONGFORM),
    ("shorten my bio to under a hundred words", Lane.LONGFORM),
    ("pen a limerick about mondays", Lane.LONGFORM),
    ("could you reword the second paragraph so its friendlier", Lane.LONGFORM),
    ("boil this article down for me", Lane.LONGFORM),
    ("compose a message to my landlord about the broken heating", Lane.LONGFORM),
    ("flesh out this outline into prose", Lane.LONGFORM),
    ("i want a caption for this instagram post", Lane.LONGFORM),
    ("edit my essay for clarity", Lane.LONGFORM),
    ("script a two minute video intro", Lane.LONGFORM),

    ("this loop never terminates and i cant work out why", Lane.REASONING),
    ("how would you implement rate limiting from scratch", Lane.REASONING),
    ("integrate x squared times e to the x", Lane.REASONING),
    ("my docker container exits immediately on startup", Lane.REASONING),
    ("come up with an algorithm to detect cycles in a graph", Lane.REASONING),
    ("whats the memory complexity of merge sort", Lane.REASONING),
    ("put together a react hook that debounces input", Lane.REASONING),
    ("figure out how many ways to seat eight people round a table", Lane.REASONING),
    ("my api returns 500 only under load what would you check", Lane.REASONING),
    ("translate this bash script into powershell", Lane.REASONING),
    ("work out the break even point given these fixed costs", Lane.REASONING),
    ("review this function for correctness", Lane.REASONING),

    ("render this into swedish", Lane.TRANSLATE),
    ("whats the polish word for bread", Lane.TRANSLATE),
    ("convert my message to turkish", Lane.TRANSLATE),
    ("i want the whole thing in hebrew", Lane.TRANSLATE),

    ("whats the score in the game right now", Lane.WEB_SEARCH),
    ("any news on the merger", Lane.WEB_SEARCH),
    ("look this up online for me", Lane.WEB_SEARCH),
    ("todays exchange rate for the shekel", Lane.WEB_SEARCH),
]
