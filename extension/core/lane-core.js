/*
 * lane-core.js — GENERATED. Do not edit; edit the Python and re-run
 * `python tools/build_core.py`.
 *
 * The classifier, the catalog and the policy, in the browser, with no server.
 *
 * This exists so the panel works the moment somebody installs the extension:
 * no Python, no terminal, no process to keep running. That was the single
 * biggest thing standing between this and anyone actually using it — a person
 * who has to clone a repository before they see a suggestion never sees one.
 *
 * It is generated rather than written because two copies of a classifier drift,
 * and advice that differs depending on which half of the product you asked is
 * worse than advice that is merely wrong. The corpus, the regexes, the lane
 * table and the model catalog are all read out of the Python at build time, and
 * tests/test_core_parity.py fails if the two ever disagree on the held-out set.
 *
 * Everything runs locally and costs nothing: no model is called to decide which
 * model to call, here or anywhere else in this product.
 */

const LaneCore = (() => {
  "use strict";

  const FENCE = /```|^\s*(def |class |function |const |let |var |import |from \w+ import|#include|public static|SELECT .+ FROM)/m;
const TRACE = /Traceback \(most recent|^\s+at [\w.$]+\(|^\w+Error:|^\w+Exception:|panic:|Segmentation fault/m;
const THINK_HARD = /\b(think (hard|carefully|step by step)|take your time|be thorough|reason through|work through this carefully)\b/i;
const CODE_REQ = /\b(write|make|build|create|generate|give\s+me|need|want|implement|help\s+me\s+with|show\s+me|code)\b[^.?!]{0,40}?\b(code|script|function|program|app|class|method|query|regex|algorithm|component|endpoint|module|test|tests|snippet|parser|api|cli|hook|migration)\b|\b(code|script|program)\s+(this|that|it|something|me)\b|\b(in|using|with|into)\s+(python|javascript|typescript|java|c\+\+|rust|go|sql|bash|powershell|html|css|react|node)\b|\b(fix|debug|refactor|optimi[sz]e|rewrite|profile)\b[^.?!]{0,30}?\b(code|script|function|bug|error|class|query|loop|test)\b/i;
const MATH = /\b(integrate|derivative|differentiate|solve\s+for|prove\s+that|factorise|factorize|eigenvalue|matrix|logarithm)\b|\b\d+\s*[\^]\s*\d+|\b(sin|cos|tan|log|ln|sqrt)\s*\(/i;
const IMAGE_REQ = /\b(draw|paint|sketch|render|generate|create|make|design|produce|give\s+me|i\s+want|i\s+need|can\s+you\s+(?:make|create|draw|generate))\b[^.?!]{0,60}?\b(image|images|picture|pictures|photo|photos|photograph|logo|logos|illustration|drawing|artwork|poster|icon|icons|banner|wallpaper|thumbnail|mockup|avatar|sticker|painting|portrait|comic|meme)\b|\b(an?\s+(?:image|picture|photo|illustration|drawing|painting|logo)\s+of)\b|\b(text[\s-]?to[\s-]?image|image\s+generation)\b/i;
const TRANSLATE_VERB = /\b(translate|translation|translating|translated)\b|\bhow\s+(?:do|would)\s+you\s+say\b|\b(?:word|phrase|term|expression|equivalent)\s+for\b|\b(?:say|write|put|render|convert)\s+(?:this|that|it|the\s+following|my\s+\w+)\s+(?:in|into|to)\b|\b(?:in|into|to|from)\s+(?:indonesian|lithuanian|portuguese|vietnamese|bulgarian|cantonese|hungarian|icelandic|norwegian|ukrainian|croatian|estonian|filipino|japanese|mandarin|romanian|bengali|catalan|chinese|english|finnish|italian|latvian|persian|punjabi|russian|serbian|spanish|swahili|swedish|tagalog|turkish|yiddish|arabic|basque|danish|french|german|hebrew|korean|polish|slovak|telugu|czech|dutch|farsi|greek|hindi|irish|latin|malay|tamil|welsh|thai|urdu)\b/i;
const LOOKUP = /\b(search|look)\s+(?:the\s+web|online|the\s+internet|it\s+up|this\s+up|that\s+up|for\s+me)\b|\bgoogle\s+(?:it|that|this|for)\b|\b(?:latest|current|today'?s|tonight'?s|this\s+week'?s|recent)\s+(?:\w+\s+){0,2}(?:news|headlines?|price|prices|score|scores|weather|forecast|results?|release|version|rate|rates|update|updates|stock|standings|exchange\s+rate)\b|\bnews\s+(?:about|on|from)\b|\bwhat'?s\s+(?:happening|going\s+on|new)\b|\b(?:right\s+now|as\s+of\s+(?:today|now|this\s+morning))\b|\bwho\s+won\s+the\b|\b(?:is|are|was|were)\s+.{0,25}\b(?:still|currently)\s+(?:open|available|running|down|up)\b|\bhow\s+much\s+(?:is|does).{0,25}\b(?:cost|trading|worth)\s+(?:now|today)\b/i;
const CODE_VERB = /\b(fix|debug|refactor|optimi[sz]e|rewrite|profile|port|migrate|implement|write|convert|translate|review|explain)\b/i;
const TOKEN = /[a-z']+/i;
const FOREIGN = /[֐-׿؀-ۿͰ-ϿЀ-ӿऀ-ॿ฀-๿぀-ヿ㐀-鿿가-힯]/;
const LATIN_LETTER = /[A-Za-z]/;
const DENSE = /[぀-ヿ㐀-鿿가-힯฀-๿]/;
const FOREIGN_ASK = /(?<![A-Za-z֐-׿؀-ۿͰ-ϿЀ-ӿऀ-ॿ])(?:מה|מהו|מהי|למה|מדוע|איך|כיצד|מתי|איפה|היכן|האם|כמה|מי|ما|ماذا|لماذا|كيف|متى|أين|هل|كم|что|почему|зачем|как|когда|где|кто|сколько|какой|що|чому|як|τι|γιατί|πώς|πότε|πού|ποιος|क्या|क्यों|कैसे|कब|कहाँ|कौन)(?![A-Za-z֐-׿؀-ۿͰ-ϿЀ-ӿऀ-ॿ])|(?:อะไร|ทำไม|อย่างไร|なぜ|なんで|どう|どこ|いつ|誰|什么|什麼|为什么|為什麼|怎么|怎麼|如何|哪里|哪裡|多少|왜|어떻게|무엇|언제|어디)/;
const FOREIGN_WHY = /(?<![A-Za-z֐-׿؀-ۿͰ-ϿЀ-ӿऀ-ॿ])(?:למה|מדוע|הסבר|תסביר|שגיאה|באג|תקלה|لماذا|اشرح|خطأ|почему|зачем|объясни|ошибка|γιατί|σφάλμα|क्यों|समझाओ)(?![A-Za-z֐-׿؀-ۿͰ-ϿЀ-ӿऀ-ॿ])|(?:ทำไม|อธิบาย|なぜ|なんで|説明|エラー|为什么|為什麼|解释|解釋|错误|錯誤|报错|왜|설명|오류|에러)/;
const FOREIGN_WRITE = /(?<![A-Za-z֐-׿؀-ۿͰ-ϿЀ-ӿऀ-ॿ])(?:כתוב|תכתוב|סכם|תסכם|נסח|اكتب|لخص|مقال|напиши|составь|статья|γράψε|περίληψη|लिखो|सारांश)(?![A-Za-z֐-׿؀-ۿͰ-ϿЀ-ӿऀ-ॿ])|(?:เขียน|สรุป|書いて|作成|要約|まとめて|写|寫|撰写|总结|總結|摘要|써줘|작성|요약)/;
const FOREIGN_TRANSLATE = /(?<![A-Za-z֐-׿؀-ۿͰ-ϿЀ-ӿऀ-ॿ])(?:תרגם|תרגום|ترجم|ترجمة|переведи|перевод|μετάφρασε|अनुवाद)(?![A-Za-z֐-׿؀-ۿͰ-ϿЀ-ӿऀ-ॿ])|(?:แปล|翻訳|訳して|翻译|翻譯|번역)/;

  const D = {
 "LANES": {
  "trivial": {
   "label": "Trivial",
   "floor": 0,
   "needs": [],
   "kind": "chat",
   "prefers": "speed",
   "wants": "speed",
   "fit": "answers instantly and there is nothing here a larger model would do differently",
   "expected_output": 30
  },
  "simple": {
   "label": "Simple",
   "floor": 40,
   "needs": [],
   "kind": "chat",
   "prefers": "speed",
   "wants": "speed",
   "fit": "recall is not where models differ — this one returns the fact fastest",
   "expected_output": 120
  },
  "general": {
   "label": "General",
   "floor": 60,
   "needs": [],
   "kind": "chat",
   "prefers": "value",
   "wants": "prose",
   "fit": "explains clearly, which is what this needs more than raw capability",
   "expected_output": 550
  },
  "longform": {
   "label": "Long-form",
   "floor": 70,
   "needs": [],
   "kind": "chat",
   "prefers": "prose",
   "wants": "prose",
   "fit": "the strongest writing voice available to you",
   "expected_output": 900
  },
  "reasoning": {
   "label": "Reasoning",
   "floor": 85,
   "needs": [],
   "kind": "chat",
   "prefers": "depth",
   "wants": "depth",
   "fit": "thinks before answering, which is the whole difference on a problem like this",
   "expected_output": 1200
  },
  "vision": {
   "label": "Vision",
   "floor": 60,
   "needs": [
    "vision"
   ],
   "kind": "chat",
   "prefers": "depth",
   "wants": "vision",
   "fit": "reads images as well as text",
   "expected_output": 400
  },
  "translate": {
   "label": "Translate",
   "floor": 55,
   "needs": [],
   "kind": "chat",
   "prefers": "prose",
   "wants": "prose",
   "fit": "handles idiom and register, which is where translations actually go wrong",
   "expected_output": 400
  },
  "web_search": {
   "label": "Look it up",
   "floor": 60,
   "needs": [
    "web"
   ],
   "kind": "chat",
   "prefers": "value",
   "wants": "web",
   "fit": "can search rather than answer from memory",
   "expected_output": 700
  },
  "image_gen": {
   "label": "Make an image",
   "floor": 0,
   "needs": [
    "image_out"
   ],
   "kind": "image",
   "prefers": "depth",
   "wants": "image",
   "fit": "actually draws, which no chat model does",
   "expected_output": 0
  },
  "tools": {
   "label": "Tools",
   "floor": 70,
   "needs": [
    "tools"
   ],
   "kind": "chat",
   "prefers": "depth",
   "wants": "tools",
   "fit": "emits well-formed tool calls, which matters more here than being clever",
   "expected_output": 600
  }
 },
 "ORDER": [
  "trivial",
  "simple",
  "translate",
  "general",
  "web_search",
  "longform",
  "reasoning"
 ],
 "LADDER": [
  "trivial",
  "simple",
  "general",
  "longform",
  "reasoning"
 ],
 "DEFAULT_LANE": "general",
 "TRAIN": [
  [
   "hey",
   "trivial"
  ],
  [
   "hi there",
   "trivial"
  ],
  [
   "morning",
   "trivial"
  ],
  [
   "good evening",
   "trivial"
  ],
  [
   "thanks!",
   "trivial"
  ],
  [
   "thank you so much",
   "trivial"
  ],
  [
   "cheers",
   "trivial"
  ],
  [
   "ta",
   "trivial"
  ],
  [
   "ok",
   "trivial"
  ],
  [
   "okay cool",
   "trivial"
  ],
  [
   "got it",
   "trivial"
  ],
  [
   "understood",
   "trivial"
  ],
  [
   "yes",
   "trivial"
  ],
  [
   "no",
   "trivial"
  ],
  [
   "yep",
   "trivial"
  ],
  [
   "nope",
   "trivial"
  ],
  [
   "sure",
   "trivial"
  ],
  [
   "nevermind",
   "trivial"
  ],
  [
   "nvm forget it",
   "trivial"
  ],
  [
   "never mind then",
   "trivial"
  ],
  [
   "lol",
   "trivial"
  ],
  [
   "haha nice",
   "trivial"
  ],
  [
   "perfect thanks",
   "trivial"
  ],
  [
   "great",
   "trivial"
  ],
  [
   "sounds good",
   "trivial"
  ],
  [
   "works for me",
   "trivial"
  ],
  [
   "bye",
   "trivial"
  ],
  [
   "goodnight",
   "trivial"
  ],
  [
   "see ya",
   "trivial"
  ],
  [
   "stop",
   "trivial"
  ],
  [
   "wait",
   "trivial"
  ],
  [
   "hold on",
   "trivial"
  ],
  [
   "carry on",
   "trivial"
  ],
  [
   "go ahead",
   "trivial"
  ],
  [
   "try again",
   "trivial"
  ],
  [
   "do it",
   "trivial"
  ],
  [
   "what is the capital of peru",
   "simple"
  ],
  [
   "whats the boiling point of water in fahrenheit",
   "simple"
  ],
  [
   "define entropy",
   "simple"
  ],
  [
   "what does api stand for",
   "simple"
  ],
  [
   "who wrote pride and prejudice",
   "simple"
  ],
  [
   "how many bytes are in a gigabyte",
   "simple"
  ],
  [
   "how tall is mount everest",
   "simple"
  ],
  [
   "when did the berlin wall fall",
   "simple"
  ],
  [
   "how do you spell accommodate",
   "simple"
  ],
  [
   "whats 40 miles in kilometres",
   "simple"
  ],
  [
   "convert 200 grams to ounces",
   "simple"
  ],
  [
   "what timezone is berlin in",
   "simple"
  ],
  [
   "whats the chemical symbol for tin",
   "simple"
  ],
  [
   "who is ada lovelace",
   "simple"
  ],
  [
   "what language do they speak in brazil",
   "simple"
  ],
  [
   "whats the plural of octopus",
   "simple"
  ],
  [
   "what year was python released",
   "simple"
  ],
  [
   "is a tomato a fruit",
   "simple"
  ],
  [
   "what does the acronym ram mean",
   "simple"
  ],
  [
   "how many continents are there",
   "simple"
  ],
  [
   "whats the currency of denmark",
   "simple"
  ],
  [
   "give me a synonym for happy",
   "simple"
  ],
  [
   "what is the speed of light",
   "simple"
  ],
  [
   "whats the difference between http and https",
   "simple"
  ],
  [
   "what does git clone do",
   "simple"
  ],
  [
   "what is a palindrome",
   "simple"
  ],
  [
   "who painted the starry night",
   "simple"
  ],
  [
   "whats the longest river in africa",
   "simple"
  ],
  [
   "abbreviation for california",
   "simple"
  ],
  [
   "how does a refrigerator actually work",
   "general"
  ],
  [
   "explain how vaccines work",
   "general"
  ],
  [
   "whats the deal with sourdough starters",
   "general"
  ],
  [
   "i dont really understand what a vpn does",
   "general"
  ],
  [
   "can you walk me through how compound interest works",
   "general"
  ],
  [
   "why do cats purr",
   "general"
  ],
  [
   "whats a good way to learn guitar as an adult",
   "general"
  ],
  [
   "should i buy or rent in this market",
   "general"
  ],
  [
   "give me some ideas for a birthday present for my dad",
   "general"
  ],
  [
   "what are the pros and cons of electric cars",
   "general"
  ],
  [
   "how do i get better at public speaking",
   "general"
  ],
  [
   "tell me about the roman empire",
   "general"
  ],
  [
   "whats the history of the olympics",
   "general"
  ],
  [
   "how should i prepare for a job interview",
   "general"
  ],
  [
   "whats a reasonable weekly running plan for a beginner",
   "general"
  ],
  [
   "i want to start cooking more what should i learn first",
   "general"
  ],
  [
   "explain the difference between weather and climate",
   "general"
  ],
  [
   "why is the sky blue",
   "general"
  ],
  [
   "how does noise cancelling work",
   "general"
  ],
  [
   "what should i look for when buying a used car",
   "general"
  ],
  [
   "recommend me some books like dune",
   "general"
  ],
  [
   "how do i keep houseplants alive",
   "general"
  ],
  [
   "whats the best way to learn a language",
   "general"
  ],
  [
   "talk me through how mortgages work in general",
   "general"
  ],
  [
   "what causes inflation",
   "general"
  ],
  [
   "is it worth getting a standing desk",
   "general"
  ],
  [
   "how do solar panels work",
   "general"
  ],
  [
   "whats the point of stretching before exercise",
   "general"
  ],
  [
   "give me advice on moving to a new city",
   "general"
  ],
  [
   "how do airlines decide ticket prices",
   "general"
  ],
  [
   "write a short story about a lighthouse keeper",
   "longform"
  ],
  [
   "draft an email declining the meeting politely",
   "longform"
  ],
  [
   "summarise this report for my boss",
   "longform"
  ],
  [
   "rewrite this paragraph in a warmer tone",
   "longform"
  ],
  [
   "compose a poem about winter",
   "longform"
  ],
  [
   "outline a blog post about remote work",
   "longform"
  ],
  [
   "write a cover letter for this job",
   "longform"
  ],
  [
   "can you make this sound less corporate",
   "longform"
  ],
  [
   "tidy up my wording here",
   "longform"
  ],
  [
   "condense this into three bullet points",
   "longform"
  ],
  [
   "make the intro punchier",
   "longform"
  ],
  [
   "turn these notes into something readable",
   "longform"
  ],
  [
   "give me the gist of the text below",
   "longform"
  ],
  [
   "write release notes for these changes",
   "longform"
  ],
  [
   "rephrase this so it doesnt sound rude",
   "longform"
  ],
  [
   "draft a speech for the opening ceremony",
   "longform"
  ],
  [
   "i need three paragraphs on renewable energy",
   "longform"
  ],
  [
   "make it longer and more dramatic",
   "longform"
  ],
  [
   "proofread this and fix the grammar",
   "longform"
  ],
  [
   "write a product description for this listing",
   "longform"
  ],
  [
   "tighten this up its far too wordy",
   "longform"
  ],
  [
   "give me a linkedin post about the launch",
   "longform"
  ],
  [
   "write the readme intro for this project",
   "longform"
  ],
  [
   "summarize the transcript i pasted below",
   "longform"
  ],
  [
   "polish the ending it feels flat",
   "longform"
  ],
  [
   "draft an apology message to a customer",
   "longform"
  ],
  [
   "write a toast for my sisters wedding",
   "longform"
  ],
  [
   "expand this bullet into a full paragraph",
   "longform"
  ],
  [
   "give me a punchy tagline for the brand",
   "longform"
  ],
  [
   "why is my recursive fibonacci so slow",
   "reasoning"
  ],
  [
   "prove that the square root of two is irrational",
   "reasoning"
  ],
  [
   "whats the time complexity of quicksort",
   "reasoning"
  ],
  [
   "refactor this class to use dependency injection",
   "reasoning"
  ],
  [
   "solve for x three x squared plus two x minus five",
   "reasoning"
  ],
  [
   "my unit test is failing and i cant see why",
   "reasoning"
  ],
  [
   "write a regex that matches balanced parentheses",
   "reasoning"
  ],
  [
   "theres a race condition somewhere in this code",
   "reasoning"
  ],
  [
   "write me a function that reverses a linked list",
   "reasoning"
  ],
  [
   "build a script to rename all these files",
   "reasoning"
  ],
  [
   "make a class for handling user sessions",
   "reasoning"
  ],
  [
   "generate a sql query for monthly revenue totals",
   "reasoning"
  ],
  [
   "i need a python script that reads a csv",
   "reasoning"
  ],
  [
   "give me the code for a rest endpoint",
   "reasoning"
  ],
  [
   "write unit tests for this module",
   "reasoning"
  ],
  [
   "find the bug in my binary search",
   "reasoning"
  ],
  [
   "why does this deadlock",
   "reasoning"
  ],
  [
   "optimise this query its taking eight seconds",
   "reasoning"
  ],
  [
   "whats wrong with my sql join",
   "reasoning"
  ],
  [
   "how do i make this thread safe",
   "reasoning"
  ],
  [
   "what edge cases am i missing here",
   "reasoning"
  ],
  [
   "calculate the monthly payment on a 300k mortgage at 5 percent",
   "reasoning"
  ],
  [
   "should this be a set or a dict for performance",
   "reasoning"
  ],
  [
   "trace through this and tell me where it goes wrong",
   "reasoning"
  ],
  [
   "design the database schema for a booking system",
   "reasoning"
  ],
  [
   "is this o n log n or o n squared",
   "reasoning"
  ],
  [
   "work out the probability of three heads in five flips",
   "reasoning"
  ],
  [
   "debug the login flow its rejecting valid users",
   "reasoning"
  ],
  [
   "plan the architecture for a multi tenant saas app",
   "reasoning"
  ],
  [
   "convert this recursive function to an iterative one",
   "reasoning"
  ],
  [
   "explain why this returns the wrong sign",
   "reasoning"
  ],
  [
   "derive the formula for compound interest",
   "reasoning"
  ],
  [
   "how much memory does this data structure actually use",
   "reasoning"
  ],
  [
   "figure out the big o of this nested loop",
   "reasoning"
  ],
  [
   "theres an off by one error somewhere in here",
   "reasoning"
  ],
  [
   "pen something short about autumn",
   "longform"
  ],
  [
   "draft a quick note to the team",
   "longform"
  ],
  [
   "edit my personal statement",
   "longform"
  ],
  [
   "shorten this to fit a tweet",
   "longform"
  ],
  [
   "caption for a photo of the beach",
   "longform"
  ],
  [
   "subject line for this email",
   "longform"
  ],
  [
   "script the voiceover for the ad",
   "longform"
  ],
  [
   "blurb for the back of the book",
   "longform"
  ],
  [
   "reword the opening line",
   "longform"
  ],
  [
   "a haiku about traffic",
   "longform"
  ],
  [
   "trim my resume to one page",
   "longform"
  ],
  [
   "headline for the press release",
   "longform"
  ],
  [
   "paraphrase this quote",
   "longform"
  ],
  [
   "write vows for the ceremony",
   "longform"
  ],
  [
   "give it a friendlier sign off",
   "longform"
  ],
  [
   "the container keeps restarting on deploy",
   "reasoning"
  ],
  [
   "requests time out only when traffic spikes",
   "reasoning"
  ],
  [
   "the build passes locally but fails in ci",
   "reasoning"
  ],
  [
   "users are getting logged out at random",
   "reasoning"
  ],
  [
   "memory climbs until the process is killed",
   "reasoning"
  ],
  [
   "the page takes nine seconds to load now",
   "reasoning"
  ],
  [
   "data comes back in the wrong order sometimes",
   "reasoning"
  ],
  [
   "review this for correctness before i ship it",
   "reasoning"
  ],
  [
   "check my logic here",
   "reasoning"
  ],
  [
   "audit this for security problems",
   "reasoning"
  ],
  [
   "compare these two approaches and pick one",
   "reasoning"
  ],
  [
   "what would you check first if this was slow",
   "reasoning"
  ],
  [
   "how would you implement caching for this",
   "reasoning"
  ],
  [
   "estimate how long this will take to run",
   "reasoning"
  ],
  [
   "port this from one framework to another",
   "reasoning"
  ],
  [
   "the numbers dont add up in this spreadsheet",
   "reasoning"
  ],
  [
   "work out which of these is cheaper over five years",
   "reasoning"
  ],
  [
   "tell me a bit about ancient egypt",
   "general"
  ],
  [
   "id like to know more about black holes",
   "general"
  ],
  [
   "curious how auctions actually work",
   "general"
  ],
  [
   "give me an overview of the french revolution",
   "general"
  ],
  [
   "whats the story with the space race",
   "general"
  ],
  [
   "suggest some ways to sleep better",
   "general"
  ],
  [
   "any tips for a first time flyer",
   "general"
  ],
  [
   "thoughts on whether i should get a dog",
   "general"
  ],
  [
   "help me decide between these two holidays",
   "general"
  ],
  [
   "whats it like living in norway",
   "general"
  ],
  [
   "explain what an index fund is for a beginner",
   "general"
  ],
  [
   "how do people usually train for a marathon",
   "general"
  ],
  [
   "population of iceland",
   "simple"
  ],
  [
   "capital city of mongolia",
   "simple"
  ],
  [
   "boiling point of ethanol",
   "simple"
  ],
  [
   "which country has the most islands",
   "simple"
  ],
  [
   "which is heavier gold or lead",
   "simple"
  ],
  [
   "what year did the euro launch",
   "simple"
  ],
  [
   "how many players on a rugby team",
   "simple"
  ],
  [
   "how far is the moon",
   "simple"
  ],
  [
   "inventor of the telephone",
   "simple"
  ],
  [
   "largest desert in the world",
   "simple"
  ],
  [
   "atomic number of carbon",
   "simple"
  ],
  [
   "when is the summer solstice",
   "simple"
  ],
  [
   "makes sense",
   "trivial"
  ],
  [
   "fair enough",
   "trivial"
  ],
  [
   "cool",
   "trivial"
  ],
  [
   "nice one",
   "trivial"
  ],
  [
   "cheers for that",
   "trivial"
  ],
  [
   "thanks a lot mate",
   "trivial"
  ],
  [
   "right ok",
   "trivial"
  ],
  [
   "go on then",
   "trivial"
  ],
  [
   "skip it",
   "trivial"
  ],
  [
   "same",
   "trivial"
  ],
  [
   "translate this sql query into an orm call",
   "reasoning"
  ],
  [
   "convert this python function to javascript",
   "reasoning"
  ],
  [
   "port this module from java to kotlin",
   "reasoning"
  ],
  [
   "rewrite these bash commands for powershell",
   "reasoning"
  ],
  [
   "turn this regex into something readable",
   "reasoning"
  ],
  [
   "show me the latest commit on that branch",
   "reasoning"
  ],
  [
   "what is the current value of this variable",
   "reasoning"
  ],
  [
   "which version of the library am i on",
   "reasoning"
  ],
  [
   "translate this paragraph into spanish",
   "translate"
  ],
  [
   "how do you say thank you in japanese",
   "translate"
  ],
  [
   "translate the following into french",
   "translate"
  ],
  [
   "can you put this in german for me",
   "translate"
  ],
  [
   "say that in hebrew",
   "translate"
  ],
  [
   "what is good morning in italian",
   "translate"
  ],
  [
   "translate this email to portuguese",
   "translate"
  ],
  [
   "i need this in arabic",
   "translate"
  ],
  [
   "translate from russian to english",
   "translate"
  ],
  [
   "how would you say that in korean",
   "translate"
  ],
  [
   "write this out in dutch please",
   "translate"
  ],
  [
   "translation of this sentence into greek",
   "translate"
  ],
  [
   "what is the latest news about the election",
   "web_search"
  ],
  [
   "search the web for reviews of this laptop",
   "web_search"
  ],
  [
   "whats the weather forecast for tomorrow",
   "web_search"
  ],
  [
   "google it for me",
   "web_search"
  ],
  [
   "who won the match last night",
   "web_search"
  ],
  [
   "current price of bitcoin",
   "web_search"
  ],
  [
   "look up the opening hours",
   "web_search"
  ],
  [
   "whats happening in the markets today",
   "web_search"
  ],
  [
   "latest release of that library",
   "web_search"
  ],
  [
   "todays headlines please",
   "web_search"
  ],
  [
   "find recent coverage of this online",
   "web_search"
  ],
  [
   "is that restaurant still open",
   "web_search"
  ]
 ],
 "MODELS": [
  {
   "id": "claude-fable-5",
   "provider": "anthropic",
   "display": "Claude Fable 5",
   "tier": 98,
   "in_price": 10.0,
   "out_price": 50.0,
   "context": 1000000,
   "max_output": 128000,
   "vision": true,
   "tools": true,
   "web": true,
   "kind": "chat",
   "image_out": false,
   "per_image": 0.0,
   "speed": 40,
   "strengths": [
    "code",
    "depth",
    "prose",
    "tools",
    "vision",
    "web"
   ]
  },
  {
   "id": "claude-opus-5",
   "provider": "anthropic",
   "display": "Claude Opus 5",
   "tier": 95,
   "in_price": 5.0,
   "out_price": 25.0,
   "context": 1000000,
   "max_output": 128000,
   "vision": true,
   "tools": true,
   "web": true,
   "kind": "chat",
   "image_out": false,
   "per_image": 0.0,
   "speed": 50,
   "strengths": [
    "code",
    "depth",
    "tools",
    "vision",
    "web"
   ]
  },
  {
   "id": "gpt-5",
   "provider": "openai",
   "display": "GPT-5",
   "tier": 94,
   "in_price": 1.25,
   "out_price": 10.0,
   "context": 400000,
   "max_output": 128000,
   "vision": true,
   "tools": true,
   "web": true,
   "kind": "chat",
   "image_out": false,
   "per_image": 0.0,
   "speed": 60,
   "strengths": [
    "code",
    "depth",
    "tools",
    "vision",
    "web"
   ]
  },
  {
   "id": "claude-opus-4-8",
   "provider": "anthropic",
   "display": "Claude Opus 4.8",
   "tier": 93,
   "in_price": 5.0,
   "out_price": 25.0,
   "context": 1000000,
   "max_output": 128000,
   "vision": true,
   "tools": true,
   "web": true,
   "kind": "chat",
   "image_out": false,
   "per_image": 0.0,
   "speed": 50,
   "strengths": [
    "code",
    "depth",
    "tools",
    "vision",
    "web"
   ]
  },
  {
   "id": "gemini-2.5-pro",
   "provider": "google",
   "display": "Gemini 2.5 Pro",
   "tier": 90,
   "in_price": 1.25,
   "out_price": 10.0,
   "context": 1048576,
   "max_output": 65536,
   "vision": true,
   "tools": true,
   "web": true,
   "kind": "chat",
   "image_out": false,
   "per_image": 0.0,
   "speed": 65,
   "strengths": [
    "depth",
    "long_context",
    "tools",
    "vision",
    "web"
   ]
  },
  {
   "id": "gpt-image-1",
   "provider": "openai",
   "display": "GPT Image 1",
   "tier": 88,
   "in_price": 0.0,
   "out_price": 0.0,
   "context": 4000,
   "max_output": 0,
   "vision": false,
   "tools": false,
   "web": false,
   "kind": "image",
   "image_out": true,
   "per_image": 0.04,
   "speed": 1,
   "strengths": [
    "image"
   ]
  },
  {
   "id": "imagen-4",
   "provider": "google",
   "display": "Imagen 4",
   "tier": 86,
   "in_price": 0.0,
   "out_price": 0.0,
   "context": 4000,
   "max_output": 0,
   "vision": false,
   "tools": false,
   "web": false,
   "kind": "image",
   "image_out": true,
   "per_image": 0.04,
   "speed": 1,
   "strengths": [
    "image"
   ]
  },
  {
   "id": "claude-sonnet-5",
   "provider": "anthropic",
   "display": "Claude Sonnet 5",
   "tier": 86,
   "in_price": 2.0,
   "out_price": 10.0,
   "context": 1000000,
   "max_output": 128000,
   "vision": true,
   "tools": true,
   "web": true,
   "kind": "chat",
   "image_out": false,
   "per_image": 0.0,
   "speed": 70,
   "strengths": [
    "code",
    "prose",
    "tools",
    "vision",
    "web"
   ]
  },
  {
   "id": "claude-sonnet-4-6",
   "provider": "anthropic",
   "display": "Claude Sonnet 4.6",
   "tier": 83,
   "in_price": 3.0,
   "out_price": 15.0,
   "context": 1000000,
   "max_output": 128000,
   "vision": true,
   "tools": true,
   "web": true,
   "kind": "chat",
   "image_out": false,
   "per_image": 0.0,
   "speed": 70,
   "strengths": [
    "code",
    "prose",
    "tools",
    "vision",
    "web"
   ]
  },
  {
   "id": "openai/gpt-oss-120b",
   "provider": "groq",
   "display": "GPT-OSS 120B",
   "tier": 80,
   "in_price": 0.037,
   "out_price": 0.17,
   "context": 131072,
   "max_output": 117964,
   "vision": false,
   "tools": true,
   "web": false,
   "kind": "chat",
   "image_out": false,
   "per_image": 0.0,
   "speed": 477,
   "strengths": [
    "code",
    "depth",
    "tools"
   ]
  },
  {
   "id": "gpt-5-mini",
   "provider": "openai",
   "display": "GPT-5 mini",
   "tier": 78,
   "in_price": 0.25,
   "out_price": 2.0,
   "context": 400000,
   "max_output": 128000,
   "vision": true,
   "tools": true,
   "web": true,
   "kind": "chat",
   "image_out": false,
   "per_image": 0.0,
   "speed": 100,
   "strengths": [
    "code",
    "speed",
    "tools",
    "vision",
    "web"
   ]
  },
  {
   "id": "dall-e-3",
   "provider": "openai",
   "display": "DALL-E 3",
   "tier": 74,
   "in_price": 0.0,
   "out_price": 0.0,
   "context": 4000,
   "max_output": 0,
   "vision": false,
   "tools": false,
   "web": false,
   "kind": "image",
   "image_out": true,
   "per_image": 0.04,
   "speed": 1,
   "strengths": [
    "image"
   ]
  },
  {
   "id": "gemini-2.5-flash",
   "provider": "google",
   "display": "Gemini 2.5 Flash",
   "tier": 74,
   "in_price": 0.3,
   "out_price": 2.5,
   "context": 1048576,
   "max_output": 65535,
   "vision": true,
   "tools": true,
   "web": true,
   "kind": "chat",
   "image_out": false,
   "per_image": 0.0,
   "speed": 140,
   "strengths": [
    "long_context",
    "speed",
    "tools",
    "vision",
    "web"
   ]
  },
  {
   "id": "openai/gpt-oss-20b",
   "provider": "groq",
   "display": "GPT-OSS 20B",
   "tier": 68,
   "in_price": 0.03,
   "out_price": 0.13,
   "context": 131072,
   "max_output": 117964,
   "vision": false,
   "tools": true,
   "web": false,
   "kind": "chat",
   "image_out": false,
   "per_image": 0.0,
   "speed": 801,
   "strengths": [
    "code",
    "speed",
    "tools"
   ]
  },
  {
   "id": "gpt-4.1-mini",
   "provider": "openai",
   "display": "GPT-4.1 mini",
   "tier": 68,
   "in_price": 0.4,
   "out_price": 1.6,
   "context": 1047576,
   "max_output": 32768,
   "vision": true,
   "tools": true,
   "web": true,
   "kind": "chat",
   "image_out": false,
   "per_image": 0.0,
   "speed": 110,
   "strengths": [
    "prose",
    "speed",
    "tools",
    "vision",
    "web"
   ]
  },
  {
   "id": "claude-haiku-4-5",
   "provider": "anthropic",
   "display": "Claude Haiku 4.5",
   "tier": 66,
   "in_price": 1.0,
   "out_price": 5.0,
   "context": 200000,
   "max_output": 64000,
   "vision": true,
   "tools": true,
   "web": true,
   "kind": "chat",
   "image_out": false,
   "per_image": 0.0,
   "speed": 120,
   "strengths": [
    "speed",
    "tools",
    "vision",
    "web"
   ]
  },
  {
   "id": "groq/compound-mini",
   "provider": "groq",
   "display": "Compound Mini",
   "tier": 65,
   "in_price": 0.15,
   "out_price": 0.6,
   "context": 131072,
   "max_output": 8192,
   "vision": false,
   "tools": true,
   "web": true,
   "kind": "chat",
   "image_out": false,
   "per_image": 0.0,
   "speed": 440,
   "strengths": [
    "tools",
    "web"
   ]
  },
  {
   "id": "qwen/qwen3.8-27b",
   "provider": "groq",
   "display": "Qwen3.8 27B",
   "tier": 64,
   "in_price": 0.425,
   "out_price": 2.55,
   "context": 1000000,
   "max_output": 131072,
   "vision": true,
   "tools": true,
   "web": false,
   "kind": "chat",
   "image_out": false,
   "per_image": 0.0,
   "speed": 470,
   "strengths": [
    "speed",
    "tools"
   ]
  },
  {
   "id": "qwen/qwen3.6-27b",
   "provider": "groq",
   "display": "Qwen3.6 27B",
   "tier": 60,
   "in_price": 0.6,
   "out_price": 3.6,
   "context": 262144,
   "max_output": 235929,
   "vision": true,
   "tools": true,
   "web": false,
   "kind": "chat",
   "image_out": false,
   "per_image": 0.0,
   "speed": 472,
   "strengths": [
    "tools",
    "vision"
   ]
  },
  {
   "id": "gpt-5-nano",
   "provider": "openai",
   "display": "GPT-5 nano",
   "tier": 52,
   "in_price": 0.05,
   "out_price": 0.4,
   "context": 400000,
   "max_output": 128000,
   "vision": true,
   "tools": true,
   "web": true,
   "kind": "chat",
   "image_out": false,
   "per_image": 0.0,
   "speed": 180,
   "strengths": [
    "speed",
    "tools",
    "vision",
    "web"
   ]
  },
  {
   "id": "gemini-2.5-flash-lite",
   "provider": "google",
   "display": "Gemini 2.5 Flash-Lite",
   "tier": 48,
   "in_price": 0.1,
   "out_price": 0.4,
   "context": 1048576,
   "max_output": 65535,
   "vision": true,
   "tools": true,
   "web": true,
   "kind": "chat",
   "image_out": false,
   "per_image": 0.0,
   "speed": 200,
   "strengths": [
    "speed",
    "tools",
    "vision",
    "web"
   ]
  }
 ],
 "CONFIDENT": 0.01,
 "UPBIAS": 0.045,
 "DOC_WORDS": 600,
 "TECH_WORDS": [
  "angular",
  "api",
  "api's",
  "array",
  "async",
  "await",
  "backend",
  "bash",
  "branch",
  "bundler",
  "cache",
  "caching",
  "class",
  "cli",
  "commit",
  "compiler",
  "container",
  "cron",
  "daemon",
  "database",
  "deadlock",
  "dependencies",
  "dependency",
  "deploy",
  "deployment",
  "dict",
  "diff",
  "django",
  "docker",
  "endpoint",
  "exception",
  "export",
  "express",
  "fastapi",
  "flask",
  "frontend",
  "func",
  "function",
  "git",
  "golang",
  "gradle",
  "hashmap",
  "haskell",
  "heap",
  "http",
  "https",
  "import",
  "index",
  "java",
  "javascript",
  "json",
  "jwt",
  "kotlin",
  "kubernetes",
  "lambda",
  "latency",
  "leak",
  "linker",
  "linter",
  "list",
  "lock",
  "maven",
  "merge",
  "method",
  "microservice",
  "middleware",
  "migration",
  "module",
  "mongo",
  "monolith",
  "mutex",
  "mysql",
  "nan",
  "nextjs",
  "npm",
  "null",
  "nullptr",
  "oauth",
  "orm",
  "package",
  "php",
  "pip",
  "pnpm",
  "pointer",
  "postgres",
  "powershell",
  "python",
  "query",
  "rails",
  "react",
  "rebase",
  "recursion",
  "redis",
  "regex",
  "repo",
  "repository",
  "ruby",
  "runtime",
  "rust",
  "scala",
  "schema",
  "segfault",
  "server",
  "serverless",
  "shell",
  "spring",
  "sql",
  "sqlite",
  "ssl",
  "stack",
  "stacktrace",
  "svelte",
  "swift",
  "tcp",
  "thread",
  "threading",
  "throughput",
  "tls",
  "traceback",
  "typescript",
  "udp",
  "undefined",
  "variable",
  "vite",
  "vue",
  "webhook",
  "webpack",
  "xml",
  "yaml",
  "yarn"
 ],
 "CREATE_WORDS": [
  "author",
  "blurb",
  "caption",
  "compose",
  "condense",
  "draft",
  "edit",
  "expand",
  "lengthen",
  "outline",
  "paraphrase",
  "pen",
  "polish",
  "proofread",
  "rephrase",
  "reword",
  "rewrite",
  "script",
  "shorten",
  "summarise",
  "summarize",
  "tagline",
  "tighten",
  "translate",
  "write"
 ],
 "FAULT_WORDS": [
  "breaks",
  "broke",
  "broken",
  "bug",
  "bugs",
  "corrupt",
  "crash",
  "crashes",
  "crashing",
  "error",
  "errors",
  "exits",
  "fail",
  "failed",
  "failing",
  "fails",
  "flaky",
  "freezes",
  "hanging",
  "hangs",
  "incorrect",
  "leak",
  "leaking",
  "mismatch",
  "regression",
  "slow",
  "stuck",
  "timeout",
  "timeouts",
  "unexpected",
  "wrong"
 ],
 "HUMAN_LANGS": [
  "arabic",
  "basque",
  "bengali",
  "bulgarian",
  "cantonese",
  "catalan",
  "chinese",
  "croatian",
  "czech",
  "danish",
  "dutch",
  "english",
  "estonian",
  "farsi",
  "filipino",
  "finnish",
  "french",
  "german",
  "greek",
  "hebrew",
  "hindi",
  "hungarian",
  "icelandic",
  "indonesian",
  "irish",
  "italian",
  "japanese",
  "korean",
  "latin",
  "latvian",
  "lithuanian",
  "malay",
  "mandarin",
  "norwegian",
  "persian",
  "polish",
  "portuguese",
  "punjabi",
  "romanian",
  "russian",
  "serbian",
  "slovak",
  "spanish",
  "swahili",
  "swedish",
  "tagalog",
  "tamil",
  "telugu",
  "thai",
  "turkish",
  "ukrainian",
  "urdu",
  "vietnamese",
  "welsh",
  "yiddish"
 ],
 "PROG_LANGS": [
  "assembly",
  "bash",
  "clojure",
  "cobol",
  "css",
  "dart",
  "elixir",
  "fortran",
  "go",
  "golang",
  "haskell",
  "html",
  "java",
  "javascript",
  "json",
  "kotlin",
  "lua",
  "matlab",
  "node",
  "perl",
  "php",
  "powershell",
  "python",
  "react",
  "regex",
  "ruby",
  "rust",
  "scala",
  "shell",
  "sql",
  "swift",
  "typescript",
  "xml",
  "yaml"
 ],
 "PROG_STRICT": [
  "bash",
  "clojure",
  "cobol",
  "css",
  "fortran",
  "golang",
  "haskell",
  "html",
  "java",
  "javascript",
  "json",
  "kotlin",
  "matlab",
  "node",
  "php",
  "powershell",
  "python",
  "react",
  "regex",
  "ruby",
  "sql",
  "typescript",
  "xml",
  "yaml"
 ]
};

  const TECH = new Set(D.TECH_WORDS);
  const CREATE = new Set(D.CREATE_WORDS);
  const FAULT = new Set(D.FAULT_WORDS);
  const HUMAN_LANGS = new Set(D.HUMAN_LANGS);
  const PROG_LANGS = new Set(D.PROG_LANGS);
  const PROG_STRICT = new Set(D.PROG_STRICT);
  const DIGITS = /\d/;
  const WORDS = /[a-z+#]+/g;

  // ── features ───────────────────────────────────────────────────────────────
  // Words plus adjacent pairs, so phrasing carries weight but no single word
  // decides, plus three domain vocabularies that survive rephrasing better than
  // any individual word does.
  function features(text) {
    const raw = String(text || "").toLowerCase();
    const all = raw.match(new RegExp(TOKEN.source, "g")) || [];
    const words = all.slice(0, 60);
    const f = new Map();
    const add = (k, n) => f.set(k, (f.get(k) || 0) + n);

    for (const w of words) add(w, 1);
    for (let i = 0; i + 1 < words.length; i++) add(words[i] + "_" + words[i + 1], 1);

    const n = words.length;
    if (n <= 2) add("<<tiny>>", 3);
    else if (n <= 5) add("<<short>>", 2);
    else if (n >= 25) add("<<long>>", 2);
    if (raw.trim().endsWith("?")) add("<<question>>", 1);

    const seen = new Set(words);
    let tech = 0;
    for (const w of seen) if (TECH.has(w)) tech++;
    if (tech) add("<<tech>>", Math.min(tech, 3));
    for (const w of seen) if (CREATE.has(w)) { add("<<create>>", 2); break; }
    for (const w of seen) if (FAULT.has(w)) { add("<<fault>>", 2); break; }
    if (DIGITS.test(raw)) add("<<numeric>>", 1);
    return f;
  }

  // ── nearest centroid over TF-IDF ───────────────────────────────────────────
  // Trained at load from the same corpus the Python uses. Roughly a millisecond
  // for two hundred examples, once, when the page loads.
  const model = { idf: new Map(), centroids: new Map() };

  function normalise(v) {
    let mag = 0;
    for (const x of v.values()) mag += x * x;
    mag = Math.sqrt(mag) || 1;
    const out = new Map();
    for (const [k, x] of v) out.set(k, x / mag);
    return out;
  }

  function vectorise(f) {
    const v = new Map();
    for (const [w, c] of f) {
      v.set(w, (1 + Math.log(c)) * (model.idf.get(w) || 1.0));
    }
    return normalise(v);
  }

  function train(samples) {
    const docs = samples.map(([t, lane]) => [features(t), lane]);
    const n = docs.length || 1;
    const df = new Map();
    for (const [f] of docs) {
      for (const w of f.keys()) df.set(w, (df.get(w) || 0) + 1);
    }
    model.idf = new Map();
    for (const [w, c] of df) {
      model.idf.set(w, Math.log((n + 1) / (c + 1)) + 1.0);
    }

    const sums = new Map();
    const counts = new Map();
    for (const [f, lane] of docs) {
      const v = vectorise(f);
      if (!sums.has(lane)) sums.set(lane, new Map());
      const bucket = sums.get(lane);
      for (const [w, x] of v) bucket.set(w, (bucket.get(w) || 0) + x);
      counts.set(lane, (counts.get(lane) || 0) + 1);
    }
    model.centroids = new Map();
    for (const [lane, bucket] of sums) {
      const c = new Map();
      for (const [w, x] of bucket) c.set(w, x / counts.get(lane));
      model.centroids.set(lane, normalise(c));
    }
  }

  function rank(text) {
    const v = vectorise(features(text));
    const scored = [];
    for (const [lane, c] of model.centroids) {
      let dot = 0;
      for (const [w, x] of c) {
        const a = v.get(w);
        if (a) dot += a * x;
      }
      scored.push([dot, lane]);
    }
    // Descending by score, then by lane name — the Python sorts tuples, so ties
    // fall back to the lane string there too. Without this the two can disagree
    // on a tie, which is exactly the drift this file exists to avoid.
    scored.sort((a, b) => (b[0] - a[0]) || (b[1] < a[1] ? -1 : b[1] > a[1] ? 1 : 0));
    return scored;
  }

  // ── tier 0 ─────────────────────────────────────────────────────────────────
  function wordsOf(text) {
    return new Set(String(text || "").toLowerCase().match(WORDS) || []);
  }

  function isTranslation(text) {
    if (!TRANSLATE_VERB.test(text)) return false;
    const w = wordsOf(text);
    for (const p of w) if (PROG_LANGS.has(p)) return false;
    for (const h of w) if (HUMAN_LANGS.has(h)) return true;
    return false;
  }

  function isCodeContext(text) {
    if (!CODE_VERB.test(text)) return false;
    const w = wordsOf(text);
    for (const p of w) if (PROG_STRICT.has(p)) return true;
    return false;
  }

  function tier0(text) {
    const t = text || "";
    if (IMAGE_REQ.test(t)) return ["image_gen", "you are asking for a picture to be made"];
    if (isTranslation(t)) return ["translate", "this is a translation between languages"];
    if (LOOKUP.test(t)) return ["web_search", "this needs current information"];
    if (TRACE.test(t)) return ["reasoning", "the message contains a stack trace"];
    if (FENCE.test(t)) return ["reasoning", "the message contains code"];
    if (THINK_HARD.test(t)) return ["reasoning", "you asked for careful reasoning"];
    if (CODE_REQ.test(t)) return ["reasoning", "this asks for code"];
    if (isCodeContext(t)) return ["reasoning", "this names a programming language"];
    if (MATH.test(t)) return ["reasoning", "this is a maths problem"];
    if (t.split(/\s+/).filter(Boolean).length > D.DOC_WORDS)
      return ["longform", "the message is document-length"];
    return [null, ""];
  }

  /* ── tier 0b: a script this vocabulary cannot read ────────────────────────
     The tokenizer is [a-z']+, so Hebrew, Arabic, Cyrillic, Greek, Devanagari,
     Thai, Kana, Han and Hangul all yield nothing. An empty feature vector
     does not abstain - it lands on the sparsest centroid, which is trivial,
     so a paragraph in any of them was being called a one-word lookup and
     dropped. Read the shape instead. Mirrors lane/classify.py.             */
  function countOf(re_, t) {
    const m = String(t || "").match(new RegExp(re_.source, re_.flags.replace("g", "") + "g"));
    return m ? m.length : 0;
  }

  function unreadable(text) {
    return countOf(FOREIGN, text) > countOf(LATIN_LETTER, text);
  }

  /* Japanese and Chinese put no spaces in, so splitting on whitespace says
     every sentence is one word long. Two characters to a word is rough, and
     the right kind of rough: it only ever tells a lookup from a question. */
  function foreignLength(text) {
    const t = text || "";
    const dense = countOf(DENSE, t);
    const spaced = t.split(/\s+/).filter(Boolean).length;
    return dense >= 4 ? Math.max(spaced, Math.floor((dense + 1) / 2)) : spaced;
  }

  function tierForeign(text) {
    const t = text || "";
    if (FOREIGN_TRANSLATE.test(t))
      return ["translate", "this asks for a translation"];
    if (FOREIGN_WRITE.test(t))
      return ["longform", "this asks for something to be written"];
    if (FOREIGN_WHY.test(t))
      return ["reasoning", "this asks why, or says something is wrong"];

    const n = foreignLength(t);
    if (FOREIGN_ASK.test(t) || t.indexOf("?") !== -1 || t.indexOf("\uff1f") !== -1)
      return [n < 5 ? "simple" : "general", "this is a question"];
    if (n >= 6) return ["general", "this is a sentence, not a search term"];
    return [null, ""];
  }

  // ── the decision ───────────────────────────────────────────────────────────
  function classify(text, opts) {
    opts = opts || {};
    const t0 = performance.now();
    const done = (lane, reason, tier, margin) => ({
      lane, reason, tier, margin: Math.round((margin || 0) * 1e4) / 1e4,
      took_us: Math.round((performance.now() - t0) * 1000),
    });

    if (opts.tools) return done("tools", "the request declares tools", "structural", 0);
    if (opts.hasImage) return done("vision", "an image is attached", "structural", 0);

    const [lane0, why0] = tier0(text);
    if (lane0) return done(lane0, why0, "0", 0);

    // Before the vocabulary gets a vote, check that it can read the alphabet.
    if (unreadable(text)) {
      const [laneF, whyF] = tierForeign(text);
      if (laneF) return done(laneF, whyF, "foreign", 0);
    }

    const scored = rank(text || "");
    if (!scored.length) return done(D.DEFAULT_LANE, "no strong signal either way", "default", 0);

    let [best, lane] = scored[0];
    const [runnerScore, runnerLane] = scored.length > 1 ? scored[1] : [0, lane];
    const margin = best - runnerScore;

    if (margin < D.CONFIDENT)
      return done(D.DEFAULT_LANE, "no strong signal either way", "default", margin);

    let reason = "how the message reads";
    // The cost asymmetry, confined to the difficulty ladder: rounding trivial
    // up to reasoning is caution, rounding a thank-you up into a web search is
    // a category error.
    const li = D.LADDER.indexOf(lane);
    const ri = D.LADDER.indexOf(runnerLane);
    if (margin < D.UPBIAS && li !== -1 && ri !== -1 && ri > li) {
      lane = runnerLane;
      reason = "how the message reads, rounded up - it was close and this is the safer half";
    }

    if (lane === "translate" && !isTranslation(text || "")) {
      const w = wordsOf(text || "");
      let isProg = false;
      for (const p of w) if (PROG_LANGS.has(p)) { isProg = true; break; }
      if (isProg) {
        lane = "reasoning";
        reason = "this moves code between languages";
      } else {
        const alt = scored.find((s) => s[1] !== "translate");
        lane = alt ? alt[1] : D.DEFAULT_LANE;
        reason = "how the message reads";
      }
    }
    return done(lane, reason, "1", margin);
  }

  // ── catalog and policy ─────────────────────────────────────────────────────
  const MODELS = D.MODELS;

  function blended(m, outRatio) {
    const r = outRatio === undefined ? 0.25 : outRatio;
    return m.in_price * (1 - r) + m.out_price * r;
  }

  function costFor(m, inTok, outTok, images) {
    if (m.kind === "image") return m.per_image * Math.max(images || 1, 1);
    return (inTok * m.in_price + outTok * m.out_price) / 1e6;
  }

  function estimateTokens(text) {
    return Math.max(1, Math.floor(String(text || "").length / 4));
  }

  function feasible(models, laneName, promptTokens) {
    const spec = D.LANES[laneName] || D.LANES[D.DEFAULT_LANE];
    const kind = spec.kind || "chat";
    return models.filter((m) => {
      if ((m.kind || "chat") !== kind) return false;
      if (kind === "image") return true;
      for (const cap of spec.needs) if (!m[cap]) return false;
      if (promptTokens && m.context < promptTokens * 1.35) return false;
      return true;
    });
  }

  function choose(laneName, mode, models, promptTokens) {
    const spec = D.LANES[laneName] || D.LANES[D.DEFAULT_LANE];
    let cand = feasible(models, laneName, promptTokens);
    if (!cand.length) return null;

    let qualified = cand.filter((m) => m.tier >= spec.floor);
    let degraded = false;
    let ranked;
    if (qualified.length) {
      if (mode === "save") {
        ranked = qualified.slice().sort((a, b) => blended(a) - blended(b) || b.tier - a.tier);
      } else if (mode === "performance") {
        const wants = spec.wants;
        ranked = qualified.slice().sort((a, b) => {
          const af = wants && a.strengths.includes(wants) ? 0 : 1;
          const bf = wants && b.strengths.includes(wants) ? 0 : 1;
          if (af !== bf) return af - bf;
          if (a.tier !== b.tier) return b.tier - a.tier;
          if (spec.prefers === "speed" && a.speed !== b.speed) return b.speed - a.speed;
          return blended(a) - blended(b);
        });
      } else {
        const value = (m) => m.tier / Math.max(blended(m), 1e-6);
        ranked = qualified.slice().sort((a, b) => value(b) - value(a) || b.tier - a.tier);
      }
    } else {
      // Nothing clears the bar, so mode stops applying: they asked for more
      // capability than exists, and the only sensible answer is the most there
      // is. Ranking by price here would answer the hardest request with the
      // weakest model.
      degraded = true;
      ranked = cand.slice().sort((a, b) => b.tier - a.tier || blended(a) - blended(b));
    }
    return { model: ranked[0], degraded, runners: ranked.slice(1, 4) };
  }

  // ── the whole advisory answer, as the panel wants it ───────────────────────
  const SITE_PROVIDER = { claude: "anthropic", chatgpt: "openai", gemini: "google" };
  const PROVIDER_SITE = { anthropic: "Claude", openai: "ChatGPT", google: "Gemini",
                          groq: "Groq", openrouter: "OpenRouter" };

  function priceWord(x) {
    if (x <= 0) return "free";
    if (x < 0.01) return "$" + x.toFixed(4);
    if (x < 1) return "$" + x.toFixed(3);
    return "$" + x.toFixed(2);
  }

  const LACKS = {
    image_gen: "No model here draws pictures - it can only read them.",
    vision: "No model here reads images.",
    tools: "No model here calls tools.",
    web_search: "No model here can search the web, so the answer would come from memory.",
  };

  const BY_LANE = {
    trivial: "There is nothing here to think about. The smallest model produces the same reply for {f}x less.",
    simple: "This is recall, not reasoning. Every model knows it; only one of them charges {f}x more to say so.",
    general: "An explanation, not a hard problem. The mid model reads the same and costs {f}x less.",
    longform: "Judged on voice rather than correctness, where the gap between models is smallest - and {f}x cheaper.",
    reasoning: "This one is worth capability, so the floor is high. Even so, you do not need the very top: {f}x less buys the same answer.",
    translate: "Translation into a major language is close to solved - this is one of the few places where the cheap model is not a compromise, and it is {f}x less.",
    web_search: "The answer is not in any model's training data, so make sure web search is switched on. Once it is, {f}x less summarises what it found just as well.",
    vision: "Reading an image needs a vision model, and the cheapest one that can see is {f}x lighter than the best.",
    tools: "Tool calls are judged on well-formed output, not brilliance. {f}x less gets you that.",
  };

  function advise(text, site, variation, allowedIds) {
    const spec = (name) => D.LANES[name] || D.LANES[D.DEFAULT_LANE];
    const verdict = classify(text);
    const laneName = verdict.lane;
    const s = spec(laneName);
    const inTok = estimateTokens(text);
    const outTok = s.expected_output;

    const provider = SITE_PROVIDER[site];
    let here = MODELS.filter((m) => !provider || m.provider === provider);
    if (allowedIds && allowedIds.length) {
      // The restriction applies only to the KIND it was expressed over.
      //
      // Somebody ticking boxes in the interview was shown chat models, so
      // their list says which chat models they can pick and nothing at all
      // about image generators. Treating it as a filter over everything made
      // "create a picture" report that none of their sites could do it while
      // listing one of their own sites as the place to go.
      const kinds = new Set(MODELS.filter((m) => allowedIds.includes(m.id))
                                  .map((m) => m.kind || "chat"));
      here = here.filter((m) => !kinds.has(m.kind || "chat")
                                || allowedIds.includes(m.id));
    }

    const out = {
      lane: laneName, lane_label: s.label, reason: verdict.reason,
      tier: verdict.tier, took_us: verdict.took_us,
      words: String(text || "").split(/\s+/).filter(Boolean).length,
      kind: s.kind, est_in: inTok, est_out: outTok,
      options: [], elsewhere: [], assuming_all: !(allowedIds && allowedIds.length),
      local: true,
    };

    const servable = here.filter((m) => {
      if ((m.kind || "chat") !== s.kind) return false;
      for (const cap of s.needs) if (!m[cap]) return false;
      return true;
    });

    if (!servable.length) {
      for (const m of MODELS) {
        if ((m.kind || "chat") !== s.kind) continue;
        let ok = true;
        for (const cap of s.needs) if (!m[cap]) { ok = false; break; }
        if (!ok) continue;
        out.elsewhere.push({
          site: PROVIDER_SITE[m.provider] || m.provider,
          provider: m.provider, id: m.id, display: m.display,
          cost: Math.round(costFor(m, inTok, outTok) * 1e6) / 1e6,
        });
      }
      out.elsewhere.sort((a, b) => a.cost - b.cost);
      out.unavailable_here = true;
      out.site_name = PROVIDER_SITE[provider] || site || "this site";
      const first = out.elsewhere[0];
      out.explain = first
        ? (LACKS[laneName] || ("No model here handles " + s.label.toLowerCase() + " work."))
          + " " + first.site + " does this with " + first.display
          + " for about " + priceWord(first.cost) + (s.kind === "image" ? " an image" : "") + "."
        : "Nothing available can do this.";
      return out;
    }

    out.unavailable_here = false;
    for (const mode of ["save", "balanced", "performance"]) {
      const d = choose(laneName, mode, here, inTok);
      if (!d) continue;
      out.options.push({
        mode, id: d.model.id, display: d.model.display, tier: d.model.tier,
        degraded: d.degraded,
        cost: Math.round(costFor(d.model, inTok, outTok) * 1e6) / 1e6,
        per_image: d.model.kind === "image",
        fit: mode === "performance" ? s.fit : "",
      });
    }

    const top = servable.reduce((a, b) => (b.tier > a.tier ? b : a));
    const wanted = (variation === "best" || variation === "performance")
      ? "performance" : "save";
    out.variation = wanted === "performance" ? "best" : "save";

    const row = out.options.find((o) => o.mode === wanted) || out.options[0];
    const rec = row ? MODELS.find((m) => m.id === row.id) : top;
    out.fit = row ? row.fit : "";

    const recCost = costFor(rec, inTok, outTok);
    const topCost = costFor(top, inTok, outTok);
    const factor = recCost > 0 ? Math.round((topCost / recCost) * 10) / 10 : 1.0;

    out.recommend = { id: rec.id, display: rec.display, tier: rec.tier,
                      cost: Math.round(recCost * 1e6) / 1e6,
                      per_image: rec.kind === "image" };
    out.top = { id: top.id, display: top.display, tier: top.tier,
                cost: Math.round(topCost * 1e6) / 1e6 };
    out.factor = factor;
    out.is_top = rec.id === top.id;
    out.saving = Math.round((topCost - recCost) * 1e6) / 1e6;

    if (out.variation === "best") {
      const save = out.options.find((o) => o.mode === "save");
      if (save && save.id !== rec.id && save.cost > 0) {
        const times = Math.round((recCost / save.cost) * 10) / 10;
        out.explain = times + "x the price of the cheapest model that would cope. "
          + "Worth it when the answer matters more than the bill; switch to SAVE when it does not.";
      } else {
        out.explain = "The cheapest model that can do this is also the one best suited to it - no trade-off here.";
      }
    } else if (out.is_top) {
      out.explain = "Nothing cheaper clears the bar for this one - the strongest model is the right call.";
    } else if (s.kind === "image") {
      out.explain = "This needs an image generator, not a chat model. "
        + rec.display + " is billed per picture, not per token.";
    } else {
      out.explain = (BY_LANE[laneName] || "").replace("{f}", factor);
    }
    return out;
  }

  train(D.TRAIN);

  return { classify, advise, choose, rank, tier0, tierForeign, foreignLength,
           features, estimateTokens,
           costFor, MODELS, LANES: D.LANES, DATA: D };
})();

if (typeof module !== "undefined" && module.exports) module.exports = LaneCore;
