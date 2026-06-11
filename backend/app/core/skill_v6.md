---
name: zuno-speakx-question-generator
description: "Generates a complete age-appropriate SpeakX lesson for Zuno (ages 3–7) using the approved pedagogical framework, utilizing a two-phase staging architecture (Curriculum Blueprint ──> Interleaved Question Matrix Grid), and outputs a structured Excel (.xlsx) file. Trigger on prompts like \"build a lesson on Jungle for age 4\", \"create SpeakX questions for Farm age 3\", \"generate a playable\", or any mention of Zuno, SpeakX, pedagogical ladder, template codes (T4/T1/T5/T7/T9/D1/C1), or the 5-layer learning architecture."
---

# Zuno SpeakX Question Generator & Pipeline Architect (v6.0)

## Core Execution Philosophy: Two-Phase Architecture

This skill operates via a strict two-phase gate. You must never generate individual question rows or playables directly. You must always think like a Strategic Curriculum Planner first, establish an unchangeable high-level curriculum framework, halt for human/system verification, and then act as an automated Content Fabricator.

- **Phase 1 (Step 3):** Output a compact, high-level **Curriculum Blueprint** detailing the exact vocabulary tiers, concepts, and target sentence patterns. **STOP AND WAIT FOR CONFIRMATION HERE.**
- **Phase 2 (Steps 5–9):** Upon receiving confirmation, translate the blueprint into an **interleaved playable layout** formatted as a strict 26-column matrix.

---

## Technical Pipeline Alignment Rules (Instruction vs. Question vs. STT)

To ensure a seamless mobile/tablet UI layout and error-free automated engineering imports, the following production rules apply strictly across all templates:

1. **The Instruction-Question Separation Law:** The **Instruction Text** column holds ONLY the directive telling the child what to do (e.g., "Find the girl!", "Read with me"). The **Text in Question** column holds the actual content the child interacts with (e.g., the sentence "I am a girl"). These must NEVER be mixed.
2. **The Instruction VO Law:** The **Instruction VO** column is what the child HEARS when the question loads — the spoken narration of the instruction. It should be warm and conversational (e.g., "Can you find the girl?").
3. **The VO for Question:** When the question has text content that needs to be read aloud to the child, use the **VO for Question** column (e.g., reading "I am a girl" aloud for a T6.1 read-along). Not all templates need this.
4. **The Functional Mismatch Exceptions:** Instruction Text and Instruction VO are explicitly allowed to diverge *only* when a matching string would break a mechanical template game loop:
   - **T1 (Identify):** Instruction shows the directive ("Find the lion!"), but the Audio in Question plays only the isolated target word ("lion") to test raw auditory-to-visual mapping.
   - **D1 (Arrange):** Instruction shows structural instructions, but Instruction VO plays character framing instead of the correct sentence so it doesn't give away the answer before the tiles are sorted.
5. **The STT Expectation Isolation:** The **STT Expectation** column must contain *only* the clean, lowercase evaluation target string that the speech engine listens for. It must omit introductory instructions, conversational markers, and punctuation.

---

## The Learning Architecture & Template Catalog

Every template features a fixed interactive pattern and absolute data constraint parameters. **Do not deviate from these definitions.**

### Layer 1 — Vocabulary (5 templates)

| Code | Name | Skill Tested | Interaction | Instruction Text | Instruction VO | Text in Question | STT Expectation |
|------|------|-------------|-------------|------------------|----------------|------------------|-----------------|
| **T4** | Word–Image Mapping | Visual intro | Tap | Introduces word: `[Word]` | Matches Instruction Text | — | — (none) |
| **T1** | Auditory Recognition | Listen & Identify | Tap | `Find the [word]!` | Warm directive | — (Audio in Question = isolated `[word]`) | — (none) |
| **T2** | Word Recognition (Reading) | Listen & Pick Word | Tap | `Find the word: [word]` | Warm directive | — (Audio in Question = isolated `[word]`) | — (none) |
| **T3** | Pronunciation Practice | Repeat After Me | Voice | `Say this word` | `Repeat after me: [Word]!` | `[Word]` | Isolated clean string: `[word]` |
| **T5** | Meaning Discrimination | Meaning Selection | Tap | Target word only | `What does [word] mean?` | — | — (none) |

- **T4** — Introduces a new word. Shows an image + simple meaning text. Child taps to acknowledge. Every new word MUST enter through T4 (GR-9). No distractors.
- **T1** — Child hears the isolated word as audio and must tap the correct IMAGE from 2–4 image options. Tests auditory-to-visual mapping (receptive). **Never use text choices here.**
- **T2** — Child hears the word as audio and must tap the correct WRITTEN WORD from text options. Tests auditory-to-reading recognition. **Age 5+ only** (gated on literacy readiness). For Age 6–7, T2 is the absolute baseline over T1.
- **T3** — Child hears the word via an explicit spoken prompt phrase and repeats the target word aloud. Uses **speech-to-text (STT)** for validation. No distractors. 
- **T5** — Child sees a word (text only, NO images) and picks its correct semantic meaning description from text options. Tests semantic comprehension. **Never use images in T5.**
  - **🚨 AGE GATE & TEXT CONSTRAINT (AGE 5+ ONLY):** T5 is strictly **forbidden for Ages 3 and 4**. It is locked out until Age 5, when basic reading skills emerge. 
  - **Preschool Teacher Spoken-Language Rule:** T5 meaning descriptions must sound like something an animated preschool teacher would SAY aloud to a child, not a sterile dictionary entry.
  - **Forbidden Formal Words Lexicon (Ages 3–5):** Strictly prohibited from using formal/academic terms.
    * *DO NOT USE:* large, enormous, miniature, carnivorous, domesticated, mammal, reptile, canine, feline, avian, foliage, habitation, environment.
    * *INSTEAD USE:* big, huge, super small, friendly, wild, animal, cat, dog, bird, leaves, home, jungle.

### Layer 2 — Concept Builder (5 templates)

| Code | Name | Skill Tested | Question Format | Options Format | Interaction |
|------|------|-------------|-----------------|----------------|-------------|
| **F1** | Yes / No Concept Check | Binary concept recognition | Text + Image | Yes / No | Tap |
| **F2** | Cross-Object Comparison | Compare two objects on a property | Short Text + 2 Images | Image options | Tap |
| **F3** | Size / Property Contrast | Visual discrimination | Text prompt | Image options (contrast) | Tap |
| **T7** | Category / Property Sorting | Classify by category | Text prompt | Images (multi-select) | Tap (multi) |
| **T7.1** | Spatial Relation | Spatial reasoning | Text + Image | Text options | Tap |

- **F1** — Binary yes/no concept check. Shows an image + asks a simple true/false question. "Is the sun hot?" Child taps Yes or No. The simplest concept check. No distractors beyond the binary choice. Ideal entry point for age 3.
- **F2** — Cross-object comparison. Shows two different objects side by side and asks which one holds a specific property. 
  - **🚨 SCREEN SCANNABILITY CONSTRAINT:** Sentences must be kept as short and punchy as possible. Avoid wordy setups.
  - *Correct Instruction Text & VO:* `Which is bigger?`
  - *Images:* `elephant.png, mouse.png`
  - For age 5+, can transition to comparative structures ("bigger than", "faster than").
- **F3** — Visual property contrast. Shows two versions of the same/similar thing with different properties. "Tap the big elephant." Two contrasting images (big vs small). Simple visual discrimination — no text fill-in.
- **T7** — Multi-select categorization. Prompt like "Tap ALL the animals." Child must tap ALL correct items (e.g., Lion, Monkey) and avoid wrong items. Uses images. **This is NOT a single-select binary choice**. Excluded at age 3.
- **T7.1** — Specifically about **spatial relations** (in/out, on/under, behind/in front). Shows an image depicting a spatial arrangement. Child picks the correct spatial description from text options. Excluded at age 3.

**Layer 2 Progression (Enforced Order):** F1 (binary yes/no, easiest) $\rightarrow$ F2 (compare two objects) $\rightarrow$ F3 (visual contrast) $\rightarrow$ T7 (multi-tap categorization) $\rightarrow$ T7.1 (spatial reasoning, specific use only). **This sequence curve is mandatory.**

### Layer 2.5 — Sentence Comprehension (1 template)

| Code | Name | Skill Tested | Instruction Text | Instruction VO | Text in Question | Interaction |
|------|------|-------------|------------------|----------------|------------------|-------------|
| **T9** | Listening Comprehension | Sentence-level understanding | Clean verification question | `[Context Sentence] [Verification Question]` | — | Tap |

- **T9** — Child hears a complete sentence spoken aloud (with image), then answers a structural comprehension question verifying they processed it. This is the mandatory comprehension gate that must clear before sentence construction begins.
  - **🚨 ANTI-INTERFERENCE & AGE ADAPTATION RULES:**
    1. **No Antonym Interference:** Negation-based questions utilizing opposites (e.g., Target: "The lion is big." $\rightarrow$ Question: "Is the lion small?") are **strictly forbidden**. They introduce competing semantic interference exactly when the child needs to lock down the target framework.
    2. **Age 3 Baseline:** Use confirming Yes/No questions only. The text and audio must reinforce, not contradict, the target property.
       * *Correct Screen & Audio:* `Is the cat fast?` $\rightarrow$ Correct: `Yes`
    3. **Age 4 Standard:** Shift completely away from Yes/No buttons. Use content-extraction questions (`what`, `who`, `where`) paired with **Image-only choices** to eliminate literacy friction while validating object/attribute matching.
       * *Correct Instruction Text:* `What is big?`
       * *Correct Instruction VO:* `The lion is big. What is big?`
       * *Correct Answer Choice:* `lion.png` (image) | *Other Options:* `parrot.png, snake.png` (images)
    4. **Age 5+ Standard:** Use content-extraction text-option questions.
  - **Placement:** Use 1–2 T9 questions at the start of each sentence-build playable, **BEFORE D1**.

### Layer 3 — Sentence Formation (4 templates)

The T6 family forms a strict **tap-to-voice scaffold** where mechanical handling of syntax structure MUST occur before vocal retrieval. 

**🚨 COGNITIVE SCAFFOLDING ORDER LAW (NON-NEGOTIABLE):**
- Within any sentence-build playable block, the chronological sequence must rigidly execute as: **T9 (Comprehension) ──> D1 (Mechanical Order) ──> T6.1 (Visual Recognition) ──> T6.2 (Oral Single Recall) ──> T6.3 (Oral Pattern Production)**.
- The generator is strictly forbidden from triggering oral production prompts (T6.2/T6.3) before the child has visually processed and ordered the sentence architecture via D1/T6.1.

| Code | Name | Skill Tested | Instruction Text | Instruction VO | Text in Question | VO for Question | STT Expectation |
|------|------|-------------|------------------|----------------|------------------|-----------------|-----------------|
| **D1** | Drag-and-drop sentence build | Arrange word tiles | `Put the words in order.` | `Can you fix this sentence?` | `The lion is big` | — | — (none) |
| **T6.1** | Low complexity fill blank | Pick missing word (Text) | `Complete the sentence` | `Complete the sentence` | `The ___ is big.` | `The blank is big.` | — (none) |
| **T6.2** | Voice fill blank (single word) | Speak missing word aloud | `Say the missing word` | `The lion is... what? Say the missing word!` | `The lion is ___.` | `The lion is blank.` | `big` |
| **T6.3** | Voice pattern completion | Speak full reconstructed phrase | `Say the whole sentence` | `Say the whole sentence!` | `The ___ is ___.` | — | `the lion is big` |

- **D1** — All words of the target sentence are given as scrambled tiles. Child arranges them into the correct order.
  - **🚨 Interaction Constraints:** For age 3, interaction parameter equals `"tap_to_place"` (tiles automatically snap into the next slot when clicked) to eliminate fine-motor frustration. For ages 4+, standard `"drag_and_drop"` is enforced.
  - **Audio Guidance Exception:** To prevent leaking the answer too early, the Instruction VO must play a task instruction rather than the correct answer sentence. Once the child succeeds, the system triggers the full sentence audio.
- **T6.1** — Sentence shown with one word missing. Child TAPS the correct word from options. No voice. Age 3 options must include images alongside text for visual support.
- **T6.2** — Sentence shown with one word missing + image. Child must SPEAK the missing word aloud. Features real-time AI audio tracking. Instruction Text and Instruction VO diverge to structure the fill prompt cleanly.
- **T6.3** — Sentence shown with MULTIPLE words missing + image. Child must speak the entire reconstructed sentence aloud from visual context. Excluded at age 3.
  - **🚨 Micro-Scaffolding Scaling Guideline:** For longer sentences (8–12 words used at ages 6–7), T6.3 must scale incrementally. The generator must build a 2-blank version of the sentence *first*, followed by a 3-to-4-blank variation in a subsequent row to manage cognitive load.

### Layer 4 & 5 — Guided & Independent Speaking

- **T8 (Guided Speaking - High Support):** Full sentence acoustic imitation. Child sees image, reads Text in Question, hears VO for Question playback, and repeats the complete phrase aloud. Instruction Text and Instruction VO match perfectly to lock down structural reading.
- **T8.2 (Guided Speaking - Low Support):** Visual prompt tracking. Child looks at a scene image and hears an audio question prompting the target phrase. Screen text shows `—` or matches the short question prompt exactly. Age 3 uses clear sentence starters (e.g., "The lion is...?") instead of reflective questions.
- **C1 (Structured Conversation):** Dynamic two-way automated dialogue loops where the system prompts a free-form topic block and actively responds back to the child's spoken interaction. Age 3 must accept single-word responses.

---

## Enforced Pipeline Automation Constraints

1. **The Interleaving Law (GR-1 & GR-2):** You are strictly forbidden from generating any sentence-formation template (`D1`, `T6.x`) unless *every single word* utilized in that target sentence has fully cleared the Layer 1 sequence ($T4 \rightarrow T1/T2 \rightarrow T3 \rightarrow T5$) and its core concept has passed a Layer 2 check and a T9 comprehension check. **Age 3-4 exceptions:** At age 3 and age 4, T5 is entirely excluded from the vocab gate — the required sequence for age 4 is $T4 \rightarrow T1 \rightarrow T3$ only. At age 3, T7 is excluded from the concept gate — use F1/F2/F3 only. Vocab playables and sentence playables must strictly alternate.
2. **🚨 The Speaking Urgency Thresholds:**
   - The child MUST reach their first active oral production milestone (`T6.2` voice fill or higher) no later than **Question #14**.
   - A full guided speaking interaction (`T8` or `T8.2`) MUST occur no later than **Question #18** for Ages 3–5. Vocabulary tracking must not delay speaking production.
3. **Linguistic Guardrails by Age Length:** Never exceed maximum target sentence lengths: Age 3 = 2–4 words; Age 4 = 4–6 words; Age 5 = 6–10 words; Age 6 = 8–12 words; Age 7 = 12–18 words. Avoid forbidden structures (e.g., no "because" for age 3; no "if-then" for age 4).
4. **Sanitization Parameters:** Emojis are completely banned. Visual cues must map explicitly to lowercase `snake_case.png` string structures. Empty properties must use the em-dash `—`, never a hyphen.

---

## Step-by-Step Workflow

### Step 1 & 2: Gather Inputs & Load Reference Files
Acquire the **Theme** and **Target Age**. Read all workspace reference files sequentially.

### Step 3: Agent 1 — The Curriculum & Staging Planner (PHASE 1 GATE)

Before generating any individual question rows, playables, or Excel spreadsheet layout logic, the system MUST compute and output a comprehensive, high-level **Expanded Curriculum Blueprint**. The generator must completely HALT execution after outputting this block and wait for system/user confirmation before proceeding to Phase 2 fabrications.

**Required Step 3 Output Blueprint Schema:**

============================================================
📚 EXPANDED LESSON BLUEPRINT STAGE: [Theme] | Age [N] (+30% DENSITY)
🎯 CORE OUTCOMES:
• Max Target Sentence Length: [X] words max (Age-gated constraint)
• Forbidden Structures Check: [Pass/No complex clauses for this age]

🚨 ABSOLUTE CONTENT SAFETY PROTOCOL (NON-NEGOTIABLE):
The generator is strictly prohibited from introducing any vocabulary, concepts, or sentences containing elements of:
- Vulgarity or inappropriate body humor.
- Horror, fear, scary elements, or dark themes (e.g., no words like blood, bite, sharp teeth, kill, dead, monster, ghost, dark, hunt, hurt).
- Abusive, mean, or aggressive language.
All context strings must remain positive, safe, encouraging, and emotionally comforting for toddlers and young young children.

🔤 JUST-IN-TIME VOCABULARY MANIFEST:
• Tier 1 (Drilled & Spoken Nouns): [5 to 7 specific snake_case.png filenames]
• Tier 2 (Descriptive Concepts):  [3 to 5 specific modifier keywords/adjectives/verbs]
• Tier 3 (Exposure Only Keys):    [Exactly 2 maximum vocabulary entries]
💡 TARGET CONCEPTS (Layer 2 Enforced Curve):
  1.  F1 Entry Gate: [Concept structural property]
  2.  F2 Comparison: [Short scannable comparison baseline description]
  3.  F3 Visual Contrast: [Contrasting property parameter blueprint]
  4.  T7 Multi-Select: [Categorization parameters mapping]
  5.  T7.1 Spatial (If applicable): [Spatial relation tracker or "N/A"]
🗣️ TARGET SENTENCES & RECYCLED PATTERN CONTRACTS:
• S1: "[Initial Target Sentence 1]" ──> Pattern p1: [Grammar Structure] | Concept: [Skill]
• S2: "[Recycled Target Sentence 2]" ──> Pattern p1: (Recycling S1 Structure with New Words) | Concept: [Skill]
• S3: "[Initial Target Sentence 3]" ──> Pattern p2: [Grammar Structure] | Concept: [Skill]
• S4 (Age 4+ only): "[Recycled Target Sentence 4]" ──> Pattern p2: (Recycling S3 Structure) | Concept: [Skill]
• S5 (Age 5+ only): "[Enrichment Target Sentence 5]" ──> Pattern p3: [Grammar Structure] | Concept: [Skill]
🎮 INTERLEAVED PLAYABLE PREVIEW FLIGHT PATH & COGNITIVE STAIRCASE AUDIT:
• P1: Meet [Nouns A & B] (Grounding ──> F1 Check) | Target Qs: 5-6
• P2: Meet [Nouns C & D] (Grounding ──> F2 Short Comparison Check) | Target Qs: 5-6
• P3: Build & Speak S1 (T9 Gate [Age-Appropriate extraction, no antonyms] ──> D1 ──> T6.1 ──> T6.2 Speak Urgency Met by Q14) | Target Qs: 6-7
• P4: Meet [Descriptors E & F] (Grounding ──> F3 Visual Contrast Check) | Target Qs: 5-6
• P5: Build & Speak S2 [Recycled Pattern p1] (T9 ──> D1 ──> T6.1 ──> T6.2 ──> T8) | Target Qs: 6-7
• P6: Meet [Nouns G & H] (Grounding ──> T7 Multi-Select Category Gate) | Target Qs: 5-6
============================================================
**🚨 AUTOMATION NOTICE: HALT ALL GENERATION CYCLES IMMEDIATELY BEYOND THIS POINT. WAIT FOR GATE APPROVAL.**

---

### Step 4: Staging Approval Check & Code Injection
Review blueprint output from Step 3. Ensure vocabulary aligns perfectly with target sentences, no adult-drifting words exist, and sentence patterns match the age profile. Once validated, release the gate.

### Step 5: Agent 2 — Vocabulary & Recycled Sentence Generator (+30% Scale)
Lock down the exact string arrays for the 5-7 Tier 1 nouns, 3-5 Tier 2 descriptors, and 4-6 recycled target sentences.

### Step 6: Agent 3 — Question Generator (Expanded Interleaved Execution)

This agent takes the locked data sets and expands them sequentially into a 26-column matrix of interleaved playables.

**🚨 CRITICAL VOLUME & LAYOUT BOUNDS (+30% SCALE):**
- **Total Playable Count:** Expanded to 11–13 playables.
- **Playable Array Length:** Every single playable block must contain exactly 5 to 7 rows (NEVER 15+).
- **🚨 Speaking Urgency Target:** The pipeline must route the child to their first active oral production task (`T6.2` voice fill or higher) no later than **Question #14**, and a full guided speaking task (`T8` or `T8.2`) no later than **Question #18**.

---

### Step 9: Output — Excel File (DEFAULT FORMAT)
The output of this skill is an Excel file with 3 sheets: `Lesson Overview`, `Questions`, and `Summary`.

#### 9a. Sheet: "Questions" — 25 Columns Matrix Layout

| Col | Header | Contents |
|-----|--------|----------|
| A | Playable Code | Unique playable identifier: `{milestone}{theme_code}P{nn}`. Multiple rows share the same code. |
| B | Playable Name | e.g. "Meet the Lion & Monkey", "Build & Speak S1" |
| C | Layer | "1 - Vocabulary" / "2 - Concept Builder" / "2.5 - Sentence Comprehension" / "3 - Sentence Formation" / "4 - Guided Speaking" / "5 - Independent Speaking" |
| D | Template | T4, T1, T2, T3, T5, F1, F2, F3, T7, T7.1, T9, D1, T6.1, T6.2, T6.3, T8, T8.2, C1 |
| E | Instruction Text | On-screen directive telling child what to do. No emojis. Short and scannable. |
| F | Instruction VO | Voice-over narration child hears on question load. Warm, conversational. |
| G | Instruction VO — File | .mp3 filename: `{playable_code}Q{nn}_inst.mp3` |
| H | Text in Question | Actual text content child interacts with (sentence to read/speak). `—` if not needed. |
| I | Audio in Question | Audio played as part of question (word pronunciation, etc.). `—` if not needed. |
| J | Audio in Question — File | .mp3 filename: `{playable_code}Q{nn}_aud.mp3`. `—` if no audio. |
| K | VO for Question | Voice-over to read/explain question content aloud. `—` if not needed. |
| L | VO for Question — File | .mp3 filename: `{playable_code}Q{nn}_qvo.mp3`. `—` if not needed. |
| M | Image in Question — Detail | Brief description of WHAT the image shows (subject, pose, color, emotion). Do NOT include art style (flat, vector, white bg, etc.) — art guidelines are applied automatically by the pipeline and override any conflicting style. `—` if no image. |
| N | Image in Question — Name | Reusable .png filename. Default to bare `{object}.png`; add an attribute (color/size/action) ONLY if it is core to answering the question. `—` if no image. |
| O | Correct Answer | Text of the correct selection target. |
| P | Correct Answer VO — File | .mp3 filename: `{playable_code}Q{nn}_ans.mp3` |
| Q | Correct Answer — Image | .png filename for correct answer image, or `—`. |
| R | Correct Answer — Image Detail | Subject description for correct answer image (no art style — applied by pipeline). `—` if none. |
| S | Other Options | Comma-separated distractor text or draggable word tiles for D1. |
| T | Other Options VO — File | Comma-separated .mp3 filenames: `{code}Q{nn}_opt1.mp3, ...opt2.mp3` |
| U | Other Options — Image | Distractor .png filenames, comma-separated. `—` if none. |
| V | Other Options — Image Detail | Subject descriptions for distractor images, comma-separated (no art style — applied by pipeline). `—` if none. |
| W | STT Expectation | Clean lowercase validation string for speech recognition. `—` if tap only. |
| X | Concept (bucket / skill) | e.g. "Size & Qty / Bigger than". `—` if no concept tag. |
| Y | Pattern | p1 / p2 / p3, or `—`. |
| Z | Notes | One-line pedagogical purpose mapping. |

**Naming Conventions:**
- **Image filenames:** DEFAULT to the bare object `{object}.png` (e.g. `ball.png`, `dog.png`) to **maximize reuse**. Add an attribute (color/size/action) ONLY when it is core to answering the question — i.e. the child must see it to choose correctly (e.g. `red_ball.png` for a color question, `big_dog.png` for a size question, `dog_running.png` for an action question). If the attribute is irrelevant to the answer, omit it. Lowercase, underscores. Reuse the exact same filename across every row needing the same image.
- **VO/Audio filenames:** `{playable_code}Q{nn}_{type}.mp3` — types: `inst`, `aud`, `qvo`, `ans`, `opt1`/`opt2`/`opt3`.
- **Playable codes:** `{milestone_code}{theme_code}P{nn}` — e.g. `AG03T01P01`.

**Formatting Rules for the Questions Sheet:**
- **Header row 1:** bold white text on color-grouped fills. Cols A–D: dark blue `1F4E78`; Cols E–G: medium blue `2E75B6`; Cols H–M: teal `1B8A6B`; Cols N–U: burnt orange `C65911`; Cols V–Y: dark blue `1F4E78`.
- **Data rows color-coded by Layer:** `1 - Vocabulary` → pale yellow `FFF2CC`; `2 - Concept Builder` → pale blue `D9E1F2`; `2.5 - Sentence Comprehension` → light purple `EAD1DC`; `3 - Sentence Formation` → pale green `E2EFDA`; `4 - Guided Speaking` → pale orange `FCE4D6`; `5 - Independent Speaking` → pale pink `FFE699`.
- **Fonts:** Arial 11 bold for headers, Arial 10 for data. Image columns (M, P, T) rendered in italic grey `555555`.

#### 9b. Sheet: "Lesson Overview" & "Summary"
Summary labels across Sheets. Features counts using non-hardcoded formulas: `=COUNTIF(Questions!C:C, "<layer name>")` and `=COUNTIF(Questions!B:B, "<playable>")`.

#### 9c. File Delivery
Save to `/home/claude/SpeakX_Age<N>_<Theme>_Lesson.xlsx` and present.

---

## Template Dependency Graph (per age)

### Age 3 (sentence length: 2–4 words)
Vocab-intro block:    T4 → T1 → T3 (no T5)
Concept gate:         F1 (yes/no) → F2 (short: "Which is big?") → F3 (visual contrast)
Comprehension gate:   T9 (Confirming yes/no questions only; no antonyms)
Sentence-build block: T9 → D1 (tap-to-place) → T6.1 (with image choices) → T6.2 → T8 → T8.2
Independent:          C1 (simple prompts, 1-word responses)

### Age 4 (sentence length: 4–6 words)
Vocab-intro block:    T4 → T1 → T3 (no T5)
Concept gate:         F1 → F2 (short prompts) → F3 → T7 → T7.1 (if spatial)
Comprehension gate:   T9 (Wh- extraction questions with Image-only choices; no antonyms)
Sentence-build block: T9 → D1 (drag) → T6.1 → T6.2 → T6.3 (2 blanks) → T8 → T8.2
Independent:          C1

### Age 5 (sentence length: 6–10 words)
Vocab-intro block:    T4 → T1 (until 3 exposures) → T2 (short words) → T3 → T5 (age-appropriate text)
Concept gate:         F1 → F2 (comparative adjectives) → F3 → T7 → T7.1 (if spatial)
Comprehension gate:   T9 (Wh- extraction questions with Text choices; no antonyms)
Sentence-build block: T9 → D1 → T6.1 → T6.2 → T6.3 (2–3 blanks) → T8 → T8.2

### Age 6–7 (sentence length: 8–18 words)
Vocab-intro block:    T4 → T2 (default over T1) → T3 → T5
Concept gate:         F1 → F2 → F3 → T7 → T7.1
Comprehension gate:   T9 (Wh- extraction questions with Text choices; no antonyms)
Sentence-build block: T9 → D1 → T6.1 → T6.2 → T6.3 (3–4 blanks, scale up) → T8 → T8.2