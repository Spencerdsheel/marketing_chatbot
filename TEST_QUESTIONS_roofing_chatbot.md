# Test Questions for Roofing Chatbot
## Manual Testing Checklist (Grounded in Knowledge Base)

Use this checklist while testing the chatbot. Check off each question as you test it. For each question, the bot should provide answers consistent with the source material from "Chatbot - Roofing Questions.md".

There's no chat-widget UI yet (that's Phase 14, not built) — testing happens via `curl` against the running
backend, one command per question. Run the setup once per session (or whenever your token expires), then
reuse the same template for every question below.

---

## Setup (run once, cmd.exe)

**1. Mint a visitor session** (30-minute TTL — re-run this if you get a 401 partway through testing):
```cmd
curl -i -X POST http://localhost:8000/widget/session -H "Content-Type: application/json" -H "Origin: http://localhost:3000" -d "{\"client_key\":\"pk_WlpgWi4qtZSZhlNP0Ce2RZKvS1U7mgbp\"}"
```
Copy `visitor_token` from the response into an env var:
```cmd
set "VT=<paste visitor_token here>"
```

**2. Confirm the tenant's LLM config is still pointed at the model you want to test** (e.g. `gpt-oss:20b-cloud`):
```cmd
docker exec chatbot-postgres psql -U chatbot -d chatbot -c "SELECT provider, model, embedding_model FROM tenant_llm_configs WHERE tenant_id='f7da0368f904444fbfbcc8902e460e39';"
```

**3. Ask a question — non-streaming** (fastest way to work through the checklist; returns `reply`,
`decision`, `confidence`, and `sources` in one shot):
```cmd
curl -s -X POST http://localhost:8000/public/chat/message -H "Content-Type: application/json" -H "Authorization: Bearer %VT%" -d "{\"message\":\"PASTE A QUESTION FROM THE CHECKLIST HERE\"}"
```

**3b. Or ask a question — streaming** (if you want to watch the response build token-by-token, matching how
the eventual widget will feel):
```cmd
curl --no-buffer -N -X POST http://localhost:8000/public/chat/message/stream -H "Content-Type: application/json" -H "Authorization: Bearer %VT%" -d "{\"message\":\"PASTE A QUESTION FROM THE CHECKLIST HERE\"}"
```

**What to check in each response:**
- `decision`: `"answer"` (grounded, confident) / `"clarify"` (mid-confidence) / `"escalate"` (low-confidence
  or off-topic — expected for the Out-of-scope section below).
- `confidence`: present (non-null) only on the `answer`/`clarify` path — `escalate` via intent-classification
  (off_topic/scheduling_request) short-circuits before RAG and shows `confidence: null`, which is normal, not
  a bug (see this session's earlier notes on the intent-classification branches).
- `sources`: for Direct/Rephrased/Multi-topic questions, expect 1+ entries with `doc_id` matching the
  ingested roofing doc. For Out-of-scope questions, `sources` should be empty or the reply should honestly
  say it doesn't know — never a confidently-invented answer.

**New conversation per question, or keep going in one thread?** Either works — omit `conversation_id` in the
body to start a fresh conversation each time (cleanest for independently grading each answer against its
source), or reuse one by adding `"conversation_id": "<id from a prior response>"` if you want to see how it
handles a multi-turn thread including working-memory context.

---

## Direct/Easy Questions
*Pull verbatim or near-verbatim from the source doc — these confirm basic RAG retrieval.*

- [ ] "How does your system find homeowners who need a new roof right now?" 
  *Source: General Questions § How does this actually work to get me jobs — Var 5*

- [ ] "What kind of budget do I need to start?" 
  *Source: General Questions § How much is this going to cost me — Var 3*

- [ ] "Once we get everything built and hit the go button, when will leads start coming in?" 
  *Source: General Questions § How fast will I see results — Var 1*

- [ ] "Do I have to sign a long-term contract?" 
  *Source: General Questions § Do I have to sign a long-term contract — Var 1*

- [ ] "Are these leads shared with five other roofing companies?" 
  *Source: General Questions § What makes you different from HomeAdvisor or Angie — Var 2*

- [ ] "Do I need a website for this to work?" 
  *Source: General Questions § Do I need a website for this to work — Var 1*

- [ ] "What information do I get with each lead?" 
  *Source: General Questions § What information do I get with each lead — Var 1*

- [ ] "How do I know the leads are actually qualified?" 
  *Source: General Questions § How do I know the leads are actually qualified — Var 1*

- [ ] "Where exactly will my ads be showing up?" 
  *Source: General Questions § Where exactly will my ads be showing up — Var 1*

- [ ] "Can you target specific neighborhoods or zip codes?" 
  *Source: General Questions § Can you target specific neighborhoods or zip codes — Var 1*

- [ ] "When will my phone start ringing with leads?" 
  *Source: Google PPC § How fast will the leads start coming in — Var 1*

- [ ] "How much is the total monthly cost for running Google Ads?" 
  *Source: Google PPC § How much is the total monthly cost for running Google Ads — Var 1*

- [ ] "What is my average Cost Per Acquisition (CPA) or cost per lead?" 
  *Source: Google PPC § What is my average Cost Per Acquisition — Var 1*

- [ ] "How does Meta actually get me roofing jobs?" 
  *Source: Meta Ads § How do Meta Ads actually get me roofing jobs — Var 1*

- [ ] "What kind of pictures or videos do I need to give you for the ads?" 
  *Source: Meta Ads § What kind of pictures or videos do I need — Var 1*

---

## Rephrased/Harder Questions
*Same underlying topics from doc, but phrased differently — tests embedding similarity & semantic understanding.*

- [ ] "What's your method for connecting homeowners with roof problems to my business?"
  *Source: General Questions § How does this actually work — different phrasing*

- [ ] "Is there flexibility in how much I spend each month, or do I need to commit to a minimum?"
  *Source: General Questions § How much budget / flexible spending — rephrased*

- [ ] "How quickly can I expect to see actual phone calls after launching?"
  *Source: General Questions § How fast will I see results — rephrased*

- [ ] "Are you the only marketing agency I'll be working with in my service area, or do you partner with my competitors too?"
  *Source: General Questions § Do I have to sign a long-term contract — territory exclusivity angle*

- [ ] "Is a high-quality website essential before we can start running ads, or can I get leads without one?"
  *Source: General Questions § Do I need a website — rephrased*

- [ ] "What details about each lead will my office receive?"
  *Source: General Questions § What information do I get with each lead — rephrased*

- [ ] "How do you prevent low-quality or tire-kicker leads from coming through?"
  *Source: General Questions § How do I know the leads are actually qualified — rephrased*

- [ ] "How fast can I pause or stop the ads if my crew gets too busy?"
  *Source: General Questions § What happens if we get too busy — rephrased*

- [ ] "What makes Google Ads different from just buying a list of leads on a lead site?"
  *Source: Google PPC § Why are Google Ads better than buying leads from HomeAdvisor — rephrased*

- [ ] "How does Google decide which ads show up first and which ones cost less per click?"
  *Source: Google PPC § What is a good Quality Score on Google — rephrased*

- [ ] "Do I need to provide raw job photos or can you help me with images?"
  *Source: Meta Ads § What kind of pictures or videos do I need — rephrased*

- [ ] "Can I run recruitment ads on Facebook at the same time as my lead-gen campaigns?"
  *Source: Meta Ads § Can you help us with our intake process / crew recruitment — rephrased*

- [ ] "Why is social media management worthwhile if it doesn't immediately ring my phone?"
  *Source: Social Media Management § Will this get me roofing leads right away — rephrased*

- [ ] "How does regular Facebook posting help people find me on Google?"
  *Source: Social Media Management § How does regular social media posting help local Google search rankings — rephrased*

- [ ] "Can you hook my website forms up to my existing roofing software like JobNimbus?"
  *Source: Website Development § Can you connect the website to my roofing CRM — rephrased*

---

## Multi-Topic / Follow-Up Questions
*Require combining info from multiple sections of the source doc.*

- [ ] "If I run both Google PPC and Meta ads at the same time, should I split my budget equally or put more into one platform?"
  *Source: Combines Google PPC § cost/budgeting + Meta Ads § cost/budgeting*

- [ ] "Can we use storm-damage landing pages on both Google Ads and Facebook, and would they need to be different?"
  *Source: Combines Google PPC § landing pages + Meta Ads § storm targeting*

- [ ] "How do social media management and paid Facebook ads work together to close more roofing jobs?"
  *Source: Combines Social Media Management § organic posts + Meta Ads § lead generation*

- [ ] "Should I invest in SEO for my website or just run paid ads if I need leads fast?"
  *Source: Combines SEO § timeline + Google PPC § speed + Website Development § SEO*

- [ ] "If you manage my social media and my Google Business Profile, how does that help my website show up higher on Google Maps?"
  *Source: Combines Social Media Management § Google Business Profile optimization + SEO § local rankings*

- [ ] "What's included in a website build, and do I need to buy paid ads to make it generate leads?"
  *Source: Combines Website Development § features + Google PPC / Meta Ads § paid strategy*

- [ ] "How do you track which roofing jobs actually came from Google ads versus Facebook ads so I know which platform to invest more in?"
  *Source: Combines Google PPC § tracking + Meta Ads § ROI tracking*

---

## Out-of-Scope / Negative-Test Questions
*Sound plausible for a roofing business chatbot but are NOT covered in this source doc — should trigger appropriate "I don't know" / escalate responses.*

- [ ] "What's the best roof material to recommend to a homeowner for a coastal, hurricane-prone property?"
  *Source: None — this is homeowner advice, not marketing/lead-gen strategy*

- [ ] "How do I apply for GAF Master Elite certification?"
  *Source: None — this is contractor credential/certification info, not marketing*

- [ ] "What should I charge per square for a residential asphalt shingle replacement in my area?"
  *Source: None — this is pricing/business operations, not lead generation*

- [ ] "How do I handle a customer complaint about roof installation quality?"
  *Source: None — this is customer service, not marketing/lead-gen*

- [ ] "What equipment and tools do my crews need to safely install a metal roof?"
  *Source: None — this is operational/safety, not marketing*

- [ ] "Do you offer liability insurance packages for roofing contractors?"
  *Source: None — this is insurance, not marketing services*

- [ ] "Can you help me negotiate better rates with my roofing material suppliers?"
  *Source: None — this is procurement, not lead generation*

- [ ] "What's the standard labor rate I should pay my roofing crews?"
  *Source: None — this is payroll/HR, not marketing*

---

## Testing Notes

**Expected Behavior for Direct/Rephrased Questions:**
- Bot should retrieve relevant chunks from the knowledge base
- Answers should be grounded in the FAQ source material
- Confidence should be high; response should feel authoritative

**Expected Behavior for Multi-Topic Questions:**
- Bot should synthesize or combine information from multiple sections
- May require a slightly longer response to address both angles
- Should not hallucinate details not in the source

**Expected Behavior for Out-of-Scope Questions:**
- Bot should gracefully indicate the question is outside its knowledge base
- Should *not* attempt to answer based on general knowledge
- Should suggest an escalation or alternative (e.g., "I'd recommend speaking with a sales expert on this")
- Should be honest about the boundary of what it knows
