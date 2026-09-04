#!/usr/bin/env python3
"""
DEEP QUESTION MODEL  ->  interactions.txt

Not a flat N*N. A taxonomy of entities across domains (substances, foods,
BEHAVIORS/lifestyle, training, systems/outcomes) + relation rules that only
emit combinations worth asking. Produces:
  - singles            (each item alone: what is it / effects / dose / evidence)
  - behavior x outcome (the non-obvious matrix: porn x focus, scrolling x dopamine, ...)
  - substance x outcome / food x outcome  (curated to relevant outcomes only)
  - substance x substance                  (same-pathway / known interactions)
  - x his meds                             (tirzepatide / tadalafil / finasteride)
  - higher-order stacks (triples+)         (real-world combos, his scenario)
  - daily-structure synthesis

Edit the maps below to extend the model, then: python3 build_questions.py
Run the output: python3 batch_ask.py interactions.txt  -> logs/coach_log_*.md
"""

OUT = {  # outcome id -> readable phrase
 "energy":"daily energy and fatigue","focus":"focus and attention","memory":"memory and learning",
 "motivation":"motivation and drive","dopamine":"dopamine regulation and reward sensitivity",
 "testosterone":"testosterone in men","dht":"DHT and 5-alpha-reductase","cortisol":"cortisol and stress",
 "prolactin":"prolactin","estradiol":"estradiol in men","thyroid":"thyroid function (T3/T4)",
 "insulin":"insulin sensitivity and blood sugar","sleep":"sleep quality and depth",
 "sleep_onset":"falling asleep and sleep onset","recovery":"muscle recovery and soreness",
 "strength":"strength and muscle hypertrophy","endurance":"endurance running performance",
 "fatloss":"fat loss while keeping muscle","libido":"libido and erectile function","mood":"mood",
 "anxiety":"anxiety","inflammation":"systemic inflammation","gut":"gut health and digestion",
 "immune":"immune resilience","hair":"scalp hair retention","skin":"skin health and acne",
 "heart":"blood pressure and cardiovascular health","hrv":"heart-rate variability",
 "bdnf":"neuroplasticity and BDNF","cravings":"sugar cravings and appetite",
 "hydration":"hydration and electrolytes","gh":"growth hormone and IGF-1",
 "attention_span":"attention span and boredom tolerance","refractory":"sexual refractory period and arousal",
}
def P(*ids): return [OUT[i] for i in ids]

qs=[]
def sec(t): qs.append("# ===== %s =====" % t)
def add(*x):
    for s in x: qs.append(s.strip())

# ---------------------------------------------------------------- BEHAVIORS
# (behavior phrase, [outcome ids])  -- the deep, non-obvious matrix
BEHAVIORS = [
 ("compulsive pornography use", ["dopamine","focus","motivation","energy","sleep","testosterone","prolactin","libido","anxiety","mood","refractory","attention_span"]),
 ("frequent ejaculation / masturbation", ["testosterone","prolactin","energy","focus","dopamine","recovery","refractory","motivation"]),
 ("semen retention / sexual abstinence", ["testosterone","focus","energy","motivation","libido","mood"]),
 ("daytime napping", ["sleep","energy","focus","cortisol","memory"]),
 ("high-stimulation phone and social-media scrolling", ["dopamine","focus","attention_span","motivation","anxiety","sleep","mood"]),
 ("using a phone in bed at night", ["sleep_onset","sleep","dopamine"]),
 ("blue-light exposure in the evening", ["sleep_onset","sleep"]),
 ("morning sunlight exposure", ["sleep","mood","energy","testosterone"]),
 ("cold-water immersion / cold showers", ["energy","mood","dopamine","recovery","inflammation","strength","fatloss"]),
 ("sauna and heat exposure", ["recovery","heart","gh","sleep","endurance"]),
 ("slow breathing / breathwork", ["cortisol","hrv","heart","focus","sleep","anxiety"]),
 ("meditation and mindfulness", ["cortisol","anxiety","focus","sleep","dopamine"]),
 ("chronic psychological stress", ["sleep","testosterone","cortisol","hair","gut","cravings","dopamine","immune","heart"]),
 ("sleep deprivation / short sleep", ["testosterone","memory","insulin","cravings","recovery","mood","immune","focus"]),
 ("alcohol intake", ["sleep","testosterone","recovery","fatloss","gut","inflammation","hydration"]),
 ("nicotine (non-combusted, e.g. pouches)", ["focus","cravings","energy","anxiety"]),
 ("time-restricted eating / intermittent fasting", ["insulin","energy","focus","testosterone","fatloss","strength"]),
 ("prolonged sitting / sedentary time", ["insulin","energy","heart","mood"]),
 ("daily walking and 10k steps (NEAT)", ["fatloss","insulin","mood","recovery","heart"]),
 ("sexual activity and orgasm", ["testosterone","prolactin","sleep","cortisol","mood"]),
 ("social connection vs isolation", ["mood","cortisol","memory","anxiety"]),
 ("hot shower or hot bath before bed", ["sleep_onset","sleep"]),
 ("evening / late training", ["sleep_onset","sleep","recovery"]),
 ("nasal breathing and mouth taping during sleep", ["sleep"]),
 ("dehydration", ["energy","focus","endurance","heart"]),
 ("doomscrolling and negative news before bed", ["anxiety","sleep_onset","cortisol"]),
 ("wireless / EMF exposure (phone in bed, Bluetooth earbuds, Wi-Fi)", ["sleep","sleep_onset","focus"]),
]

# ---------------------------------------------------------------- SUBSTANCES
SUBS = [
 ("creatine",["strength","focus","recovery","hair","dht"]),
 ("caffeine",["energy","focus","endurance","sleep","anxiety"]),
 ("L-theanine",["focus","sleep","anxiety","cortisol"]),
 ("magnesium",["sleep","insulin","cortisol","heart"]),
 ("omega-3 (EPA/DHA)",["recovery","inflammation","heart","mood"]),
 ("vitamin D",["testosterone","immune","strength","mood"]),
 ("zinc",["testosterone","immune","dht","skin"]),
 ("ashwagandha",["cortisol","sleep","testosterone","anxiety"]),
 ("rhodiola",["energy","cortisol","mood"]),
 ("beta-alanine",["endurance","strength"]),
 ("dietary nitrate (beetroot)",["endurance","heart"]),
 ("L-tyrosine",["focus","mood","cortisol"]),
 ("alpha-GPC",["focus","strength"]),
 ("citicoline",["focus","memory"]),
 ("acetyl-L-carnitine (ALCAR)",["focus","energy","endurance"]),
 ("uridine monophosphate",["focus","memory"]),
 ("NAD+/NMN",["energy","insulin","endurance"]),
 ("glutathione",["inflammation","recovery","immune"]),
 ("berberine",["insulin","fatloss"]),
 ("boron",["testosterone","dht","estradiol"]),
 ("melatonin",["sleep_onset","sleep"]),
 ("glycine",["sleep","recovery"]),
 ("tongkat ali",["testosterone","libido","cortisol"]),
 ("fenugreek",["testosterone","libido","dht"]),
 ("saw palmetto",["dht","hair"]),
 ("Semax",["focus","memory","bdnf"]),
 ("Selank",["anxiety","focus"]),
 ("bromantane",["energy","dopamine","focus"]),
 ("noopept",["focus","memory"]),
 ("BPC-157",["recovery","gut"]),
 ("MK-677 (ibutamoren)",["gh","sleep","insulin"]),
 ("tesamorelin",["fatloss","gh"]),
 ("enclomiphene",["testosterone","libido"]),
 ("kisspeptin",["testosterone","libido"]),
 ("l-carnitine",["fatloss","endurance","energy"]),
 ("curcumin",["inflammation","recovery"]),
 ("taurine",["endurance","energy","sleep"]),
 ("collagen peptides",["recovery","skin","hair"]),
 ("bovine colostrum",["gut","immune","recovery","endurance","inflammation"]),
]

# ---------------------------------------------------------------- FOODS
FOODS = [
 ("dietary carbohydrates",["energy","sleep","insulin","thyroid","endurance","focus"]),
 ("dietary protein",["recovery","fatloss","strength","cravings"]),
 ("dietary fat",["testosterone","heart","cravings"]),
 ("dietary fiber",["gut","insulin","fatloss","cravings"]),
 ("added sugar",["energy","mood","focus","insulin","dopamine","cravings","skin"]),
 ("seed / vegetable oils",["inflammation","heart"]),
 ("dairy and milk",["strength","insulin","skin","dht"]),
 ("fermented foods",["gut","immune","inflammation"]),
 ("red meat",["testosterone","inflammation","iron"] if False else ["testosterone","inflammation"]),
 ("fatty fish",["inflammation","heart","mood"]),
 ("ultra-processed foods",["cravings","insulin","inflammation","gut"]),
 ("dietary sodium / salt",["hydration","heart","endurance"]),
 ("water and hydration",["energy","focus","endurance"]),
 ("coffee (beyond caffeine)",["gut","insulin","heart"]),
]

# ---------------------------------------------------------------- BUILD
sec("SINGLES — each item on its own")
for b,_ in BEHAVIORS:
    add(f"what does the evidence say about how {b} affects the body and mind overall?")
for s,_ in SUBS:
    add(f"what is {s}, what does it do, at what dose, and how strong is the human evidence?")
for f,_ in FOODS:
    add(f"how does {f} affect the body overall, and what is the evidence-based way to use it?")

sec("BEHAVIOR x OUTCOME — the non-obvious matrix")
for b,outs in BEHAVIORS:
    for o in outs:
        add(f"how does {b} affect {OUT[o]}? What is the mechanism and how strong is the evidence?")

sec("SUBSTANCE x OUTCOME")
for s,outs in SUBS:
    for o in outs:
        add(f"how does {s} affect {OUT[o]}, at what dose, and how strong is the human evidence?")

sec("FOOD / MACRO x OUTCOME")
for f,outs in FOODS:
    for o in outs:
        add(f"how do/does {f} affect {OUT[o]}, and what does the evidence say about amount or timing?")

sec("SUBSTANCE x SUBSTANCE — same-pathway, synergy, competition, blunting")
add(
 "which minerals compete for absorption (zinc, iron, calcium, magnesium, copper) and how far apart should they be taken?",
 "does caffeine blunt creatine, and does taking them together matter?",
 "how do caffeine and L-theanine interact for focus, and what ratio works best?",
 "do high-dose antioxidants (vitamin C/E, NAC, astaxanthin, glutathione) blunt endurance and hypertrophy adaptation, and at what dose?",
 "which supplements are fat-soluble and must be taken with dietary fat (vitamin D, K2, omega-3, CoQ10, astaxanthin)?",
 "do dietary nitrate and citrulline stack for nitric oxide, or is it redundant?",
 "do beta-alanine and sodium bicarbonate stack for high-intensity buffering?",
 "how do ashwagandha and magnesium interact for night-time cortisol and sleep?",
 "do GH secretagogues (MK-677, ipamorelin, CJC-1295) worsen insulin sensitivity, conflicting with a cut?",
 "which supplements in a stack act on the same pathway and would plateau rather than add up?",
 "does combining melatonin, magnesium and glycine at night improve sleep more than any one alone?",
 "do tongkat ali, fenugreek and boron stack for testosterone, or overlap?",
)

sec("x HIS MEDS — tirzepatide / tadalafil / finasteride")
add(
 "how does tirzepatide's appetite suppression interact with hitting high protein and fueling long runs?",
 "does tirzepatide change how oral supplements are absorbed or timed?",
 "how do a calorie deficit, marathon mileage and tirzepatide together affect T3 and testosterone?",
 "is there a dangerous interaction between tadalafil and dietary nitrate, beetroot, or nitric-oxide supplements (blood pressure)?",
 "how does finasteride interact with DHT-raising supplements (fenugreek, boron, saw palmetto, creatine)?",
 "do GLP-1 drugs and alcohol interact for the liver or blood sugar?",
)

sec("HIGHER-ORDER STACKS (N-to-the-X) — real combinations & your scenario")
add(
 "combined effect: compulsive porn use + late-night phone use + short sleep on next-day dopamine, focus and motivation?",
 "combined effect: chronic stress + sugar cravings + poor sleep — how does this loop feed itself and how do I break it?",
 "combined effect: calorie deficit + high running volume + tirzepatide on testosterone, T3 and recovery together?",
 "combined effect: caffeine + L-theanine timed in the morning + a 20:15 bedtime on focus and sleep?",
 "combined effect: evening resistance training + caffeine + early bedtime on sleep onset?",
 "combined effect: morning sunlight + cold shower + no caffeine on study drive and alertness?",
 "combined effect: creatine + beta-alanine + caffeine as one pre-workout on performance and any interactions?",
 "combined effect: magnesium + glycine + ashwagandha at night on sleep depth and cortisol?",
 "combined effect: sauna then cold immersion on recovery, and does order matter?",
 "combined effect: high protein + resistance training + a GLP-1 on preserving muscle during a cut?",
 "combined effect: alcohol the night before + poor sleep on next-day testosterone, focus and training?",
 "combined effect: fasting + fasted morning training + a 10-hour workday on energy and muscle?",
 "combined effect: porn + scrolling as a stress-escape loop on motivation and deep-work focus?",
 "combined effect: omega-3 + creatine + resistance training on muscle protein synthesis and recovery?",
 "combined effect: nitrate + caffeine + beta-alanine on a hard tempo or interval run?",
 "combined effect: semen retention + heavy training + high testosterone goals — does abstinence actually help performance?",
)

sec("DAILY STRUCTURE — synthesis for building the day")
add(
 "on an early schedule with a 20:15 bedtime, what is the latest safe time for caffeine?",
 "best time of day for magnesium, glycine, and melatonin, and how long before bed?",
 "which supplements go morning vs night for my goals, and why?",
 "for evening training, exactly what to eat and supplement pre- vs post-workout?",
 "how long must minerals be separated from each other and from coffee?",
 "what should breakfast, pre-training, post-training and dinner each contain to support energy, recovery and sleep?",
 "given morning study, a 10-hour workday and evening training, what is the optimal daily timing map for my whole stack?",
 "what is the smallest daily stack + routine that covers energy, focus, recovery and sleep with no redundancy?",
 "what daily habits most raise testosterone naturally, ranked by evidence strength?",
 "what daily habits most improve deep-work focus without caffeine, ranked by evidence?",
)

sec("WEIGHT LOSS — correct, smart, sustainable")
add(
 "what is the correct and safe rate of weight loss per week, in pounds and as a percent of bodyweight, and what goes wrong when you lose faster?",
 "at 230 lb aiming for ~195, how fast can I safely lose ~35 lb and how should the cut be phased?",
 "what is the single smartest, most evidence-based approach to losing fat while keeping muscle?",
 "how large should a calorie deficit be for optimal fat loss, and at what point does a bigger deficit backfire?",
 "how do I set up a cut correctly — calories, protein, training, cardio, and step targets?",
 "how do I preserve muscle and strength during a cut, and what protein intake anchored to goal weight?",
 "what actually causes a weight-loss plateau, and how do I break one the right way?",
 "are diet breaks and refeeds worth it, and how do I run them?",
 "what is reverse dieting and does it prevent fat regain after a cut?",
 "how does losing weight too fast cause muscle loss, gallstones, or loose skin, and how do I avoid it?",
 "how do I tell whether I'm losing fat versus muscle, and what should I measure?",
 "how does a large or prolonged deficit lower testosterone and T3, and how do I protect them?",
 "how do sleep and stress determine whether a cut actually works?",
 "how do I keep the weight off long-term and avoid the regain that most people experience?",
 "is a slow cut or an aggressive cut better for reaching a lean, muscular end state?",
 "how do I track weight loss without being misled by daily water-weight swings?",
 "should fat loss come more from diet or cardio, and how much cardio is too much on a cut?",
 "what body-fat percentage is healthy, and where does low body fat start harming hormones?",
 "what is metabolic adaptation / adaptive thermogenesis, and how do I minimize it during a cut?",
)

sec("GLP-1 / TIRZEPATIDE — correct use, muscle, thyroid, safety")
add(
 "what is the correct way to lose weight on tirzepatide while minimizing muscle and lean-mass loss?",
 "how much of GLP-1 weight loss is typically lean mass, and what specifically reduces that fraction?",
 "what should I eat on tirzepatide when appetite is suppressed to still hit protein and micronutrients?",
 "how much protein per day on a GLP-1, and practical ways to consume it with very low appetite?",
 "how much resistance training is needed to protect muscle on tirzepatide?",
 "is tirzepatide safe for the thyroid, and what is the medullary thyroid cancer / C-cell warning about?",
 "what are the most common tirzepatide side effects and the correct way to manage them (nausea, constipation, GI)?",
 "how does tirzepatide affect hydration and electrolytes, and what should I do about it?",
 "does tirzepatide reduce endurance or strength performance, and how do I train around it?",
 "what is the correct dose-escalation schedule for tirzepatide and why ramp slowly?",
 "what bloodwork and vitals should I monitor while on a GLP-1?",
 "can I safely do marathon training on a GLP-1, or does under-fueling become the real danger?",
 "how do GLP-1 drugs affect the gallbladder, pancreas, and gut motility, and what are the red-flag symptoms?",
 "which supplements or peptides should NOT be combined with tirzepatide?",
 "how does tirzepatide compare to semaglutide, retatrutide, and liraglutide for weight loss and muscle retention?",
 "does tirzepatide affect testosterone, fertility, or other hormones?",
 "is there a peptide or strategy that spares muscle when paired with a GLP-1, and is it evidence-based?",
 "are there thyroid, pancreatitis, or other warning signs I should watch for on a GLP-1?",
 "should a GLP-1 be used long-term, or to reach goal weight and then stopped?",
 "what is the correct maintenance-dose strategy after reaching goal weight on tirzepatide?",
)

sec("TAPERING / GETTING OFF THINGS — the correct way to stop")
add(
 "what is the correct way to come off tirzepatide without regaining the weight, and does appetite (food noise) return?",
 "how do I taper off caffeine without the withdrawal headache and energy crash?",
 "should peptides be cycled on and off, and which ones cause rebound when stopped?",
 "what happens when you stop creatine — do you lose real gains or just water weight?",
 "what is the shed period when starting or stopping finasteride, and how do I handle it?",
 "how do I deload or take a training break without losing fitness?",
 "how do I stop melatonin or sleep aids without rebound insomnia?",
 "should ashwagandha be cycled, and is it safe to stop abruptly?",
 "do GH secretagogues (MK-677) cause a rebound or crash when stopped?",
 "what is the safest evidence-based way to quit a compulsive habit like porn or scrolling?",
 "how should someone reduce or stop alcohol safely if intake has become a problem?",
)

sec("SAFETY & CONCERNS — what to actually worry about, by category")
add(
 "what are the biggest safety concerns with research peptides — sourcing, purity, contamination, and injection?",
 "how do I verify a supplement is third-party tested (NSF, Informed Sport) and free of contaminants?",
 "which common supplements can damage the liver or kidneys at high doses?",
 "what are the real risks of megadosing vitamins A, D, E, B6, and niacin?",
 "which supplement and drug interactions are genuinely dangerous versus theoretical?",
 "what red-flag symptoms mean I should stop a supplement or peptide immediately?",
 "what bloodwork should a man in his late 20s track regularly, and how often?",
 "what are the cardiovascular risks of artificially raising testosterone or IGF-1?",
 "is elevated IGF-1 from MK-677 or IGF-1 LR3 a cancer risk?",
 "how dangerous is combining serotonergic agents (methylene blue, 5-HTP, SSRIs)?",
 "what are the dependence and withdrawal risks of phenibut?",
 "what are the melanoma and mole concerns with melanotan?",
 "which testosterone-booster herbs carry liver-toxicity concerns?",
 "what are the risks of doing too much at once — hybrid training plus a cut plus a 10-hour job?",
 "what are the early signs of low energy availability / RED-S and how do I catch it?",
 "when is a supplement stack simply too large or too many unproven things at once?",
 "what are the risks of DIY peptide injections (sterility, dosing errors, air)?",
 "when should weight loss, a symptom, or a lab value prompt seeing a doctor?",
 "what are the risks of reaching very low body fat for hormones, bone, and immunity?",
 "how do I judge whether a supplement is worth taking versus marketing hype?",
)

sec("BEST PRACTICE & RULES — the correct way to do things")
add(
 "what are the core rules for supplementing safely and effectively?",
 "how do I run a proper n=1 self-experiment — one variable, timeframe, and what to measure?",
 "what is the correct order to add supplements, and why one at a time?",
 "how do I read a study and judge whether the evidence is actually strong?",
 "which fundamentals matter far more than any supplement, ranked?",
 "how do I build a routine sustainable enough to keep for years, not weeks?",
 "what is the minimum effective dose principle and how do I apply it across supplements and training?",
 "what metrics should I track to know objectively whether my plan is working?",
 "when should I change an intervention versus give it more time?",
 "how do I prioritize interventions by evidence strength rather than hype?",
)

# templated: mistakes / best practice / monitoring across each major domain
DOMAINS={
 "fat loss on a cut":"fat loss while preserving muscle",
 "muscle gain and hypertrophy":"building muscle and strength",
 "endurance and marathon training":"endurance running performance",
 "sleep quality":"getting deep, restorative sleep",
 "focus and cognition":"deep-work focus and learning",
 "raising testosterone naturally":"optimizing natural testosterone",
 "stress and cortisol management":"managing chronic stress",
 "gut health":"gut health and digestion",
 "recovery":"recovering from training",
 "supplement stacking":"stacking supplements",
}
sec("BY DOMAIN — biggest mistakes / best practice / what to monitor")
for name,desc in DOMAINS.items():
    add(f"what are the biggest evidence-based mistakes people make with {name}?")
    add(f"what is the evidence-based best-practice hierarchy for {desc}, most to least important?")
    add(f"what should I monitor or measure to know {name} is working and stays safe?")

# ============================ GAP-FILL: what the model was missing ============================
sec("BIOMARKERS, LABS & WEARABLES — measuring the machine")
add(
 "which blood panels should a late-20s man run to actually understand his health, and how often?",
 "what are the optimal (not just 'normal') ranges for total and free testosterone, SHBG, and estradiol in a young man?",
 "how do I interpret ApoB and Lp(a), and what targets lower long-term cardiovascular risk?",
 "what do fasting insulin, fasting glucose, and HbA1c together tell me about metabolic health?",
 "what does hs-CRP tell me about inflammation, and what raises or lowers it?",
 "how do I read a full thyroid panel (TSH, free T3, free T4, reverse T3) and what's optimal?",
 "what ferritin and iron markers matter for an endurance runner, and what's too low or too high?",
 "what is the omega-3 index and what level is protective?",
 "what does homocysteine indicate and how do I lower it?",
 "how useful is a continuous glucose monitor (CGM) for a non-diabetic optimizing diet and energy?",
 "how accurate are wearables (Whoop, Oura, Apple Watch) for sleep and HRV, and how should I use the data?",
 "what does HRV actually tell me about recovery and readiness to train?",
 "how do I measure VO2max, and what number should a hybrid athlete target?",
 "how accurate are DEXA and bioimpedance for tracking body fat, and how often should I scan?",
 "which single labs give the highest signal for the money if I can only run a few?",
)
sec("GENETICS & PERSONAL RESPONSE — why the same thing works differently")
add(
 "how does CYP1A2 genotype make someone a fast or slow caffeine metabolizer, and should that change my caffeine use?",
 "what does MTHFR status mean for folate/B12 form (methylfolate) and homocysteine?",
 "how do ACTN3 and other genes affect whether I respond better to power or endurance training?",
 "what does ApoE genotype mean for saturated fat, cardiovascular, and cognitive risk?",
 "why are some people creatine non-responders, and how do I know if I am one?",
 "how much of supplement and diet response is individual variation, and how do I find what works for ME?",
 "is at-home genetic or microbiome testing (23andMe-style) actually useful for optimization, or hype?",
)
sec("ENVIRONMENT & EXPOSURES — the inputs nobody counts")
add(
 "do endocrine-disrupting chemicals (BPA, phthalates) from plastics lower testosterone, and how do I reduce exposure?",
 "does microwaving or storing food in plastic leach hormones-disrupting compounds into food?",
 "how much do microplastics accumulate in the body, and what does the evidence say about harm?",
 "does mouthwash kill the oral bacteria needed to convert dietary nitrate to nitric oxide, and does that raise blood pressure?",
 "is filtered water worth it — what contaminants (lead, PFAS, chlorine) matter and which filter removes them?",
 "does cookware matter (non-stick/Teflon, cast iron, aluminum) for health?",
 "is organic produce worth it, and which foods carry the most pesticide residue?",
 "how does air quality and indoor CO2 affect cognition and sleep, and what helps?",
 "do heavy metals in protein powders, fish, or shilajit pose a real risk, and how do I avoid them?",
 "does chronic exposure to artificial light and lack of daylight harm health beyond sleep?",
)
sec("SYMPTOM TROUBLESHOOTING — why am I feeling X and how to fix it")
add(
 "what causes brain fog, and what are the evidence-based fixes?",
 "why do I get an afternoon energy crash, and how do I prevent it?",
 "why might I feel tired even after a full night's sleep, and what to check?",
 "what causes low motivation and drive, and how do I restore it without stimulants?",
 "what causes poor recovery and lingering soreness, and how do I fix it?",
 "why has my weight loss or strength stalled, and how do I diagnose the cause?",
 "what causes low libido in a young man, and what's the workup?",
 "what causes bloating and digestive discomfort, and how do I identify the trigger?",
 "what causes nagging joint pain in a lifter who runs, and how do I address it?",
 "what causes irritability or low mood, and which inputs (sleep, sugar, stress, sunlight) drive it?",
 "what does losing morning erections indicate about health, and when to worry?",
 "why might I feel wired-but-tired at night, and how do I fix it?",
)
sec("INJURY PREVENTION, RUNNING FORM & BONE")
add(
 "what are the most common running injuries (shin splints, IT band, runner's knee, plantar fasciitis, stress fractures) and how do I prevent each?",
 "how do I ramp marathon mileage without injury (the 10% rule and alternatives)?",
 "does running cadence (~180 spm) or foot strike reduce injury risk?",
 "what does the evidence say about shoe cushioning, heel-to-toe drop, and carbon-plated shoes?",
 "how do I keep bones strong and avoid stress fractures while lean and running high mileage?",
 "does low energy availability raise stress-fracture and bone-loss risk, and how do I protect bone?",
 "what warm-up and prehab actually reduce injury for someone who lifts and runs?",
 "how do I train around a minor niggle without making it worse?",
 "does strength training reduce running injury risk, and which lifts matter most?",
 "how important are calcium, vitamin D, and vitamin K2 for bone in a young athlete?",
)
sec("TRAINING METHODOLOGY — the how of getting fitter")
add(
 "what is zone 2 training, how do I find my zone 2, and how much per week for a marathon?",
 "how do I develop VO2max, and what interval formats work best?",
 "what is polarized (80/20) training and does it beat threshold-heavy training?",
 "how do I periodize a marathon build alongside lifting to peak on race day?",
 "how do I apply progressive overload correctly for hypertrophy and strength?",
 "how close to failure should I train each set for muscle growth?",
 "how long should rest periods be for strength vs hypertrophy?",
 "how do I structure a taper before a race without losing fitness?",
 "when and how do I deload, and what are the signs I need one?",
 "does the sequence of running and lifting in the same session change results?",
 "how do I minimize the interference effect between endurance and strength?",
 "how do I use RPE and autoregulation to adjust training day to day?",
)
sec("LONGEVITY & HEALTHSPAN — playing the long game")
add(
 "what are the highest-evidence levers for lifespan and healthspan for someone in their 20s?",
 "how strongly does VO2max predict mortality, and what level should I build toward?",
 "what is autophagy, and do fasting or exercise meaningfully increase it in humans?",
 "what is the human evidence for senolytics (fisetin, spermidine) and 'anti-aging' compounds?",
 "what is the actual evidence for metformin and rapamycin as longevity drugs in healthy people?",
 "does caloric restriction extend healthspan in humans, and is it worth the tradeoffs?",
 "what do epigenetic aging clocks measure, and can lifestyle change them?",
 "what should I do in my late 20s that most pays off for health at 40 and 60?",
 "which common habits accelerate aging the most (sugar, alcohol, poor sleep, inactivity)?",
 "does muscle mass and strength in midlife predict longevity, and how much should I bank now?",
)
sec("STUDY, LEARNING & DEEP WORK — methodology")
add(
 "what spaced-repetition schedule maximizes long-term retention with Anki?",
 "how do I build and sustain deep-work focus for long coding and study sessions?",
 "does the Pomodoro technique or another structure improve sustained focus?",
 "how effective is dual-n-back or brain training for real-world cognition?",
 "does background music or noise help or hurt focus while studying or coding?",
 "how do I use exercise timing to boost learning and memory consolidation?",
 "what note-taking or knowledge systems improve retention and recall?",
 "how do I overcome procrastination in an evidence-based way?",
 "how does sleep timing relative to study affect what I remember?",
 "what is the fastest evidence-based way to learn a new technical skill?",
)
sec("FOOD DEEP-DIVES & COOKING — the non-obvious plate")
add(
 "do advanced glycation end-products (AGEs) from high-heat cooking (grilling, charring) drive inflammation, and how do I cook to reduce them?",
 "do heated or reused seed oils oxidize into harmful compounds, and does that matter?",
 "do artificial sweeteners affect gut bacteria, insulin, or appetite?",
 "does cooking versus eating raw change the nutrient value of key foods?",
 "how many eggs per day are fine, and do they raise cholesterol or ApoB?",
 "what does coffee do for health beyond caffeine (polyphenols, liver, longevity)?",
 "what are the real benefits of green tea and EGCG?",
 "do cruciferous vegetables (broccoli, sprouts) meaningfully affect estrogen or detox pathways?",
 "are berries and flavonoids worth prioritizing for brain and vascular health?",
 "how much do nuts help or hurt a cut, and which are best?",
 "is organ meat (liver) worth eating for micronutrients, and how much?",
 "how do I build the ideal plate for a high-protein cut (proportions, foods)?",
 "does meal frequency (3 meals vs grazing) matter beyond total intake?",
 "which foods are highest-ROI to add and which are highest-ROI to cut?",
)
sec("SKIN, HAIR, EYES, TEETH & POSTURE — desk-life maintenance")
add(
 "what skincare routine has real evidence (retinoids, sunscreen, vitamin C) for a man?",
 "does red-light therapy help skin, hair, or recovery, and what's the evidence?",
 "what actually reduces acne (diet, dairy, skincare)?",
 "what is the fastest evidence-based way to grow a fuller beard?",
 "how do I protect my eyes and reduce strain from all-day screens (20-20-20, lutein/zeaxanthin)?",
 "does the oral microbiome affect systemic inflammation and heart health?",
 "what daily habits best prevent cavities and gum disease and remineralize enamel?",
 "what desk setup and ergonomics prevent neck, back, and wrist (RSI) problems for a programmer?",
 "do posture, standing desks, and movement breaks actually change long-term health?",
 "is there evidence behind jaw/chewing training or is it hype?",
)
sec("SUPPLEMENT FORMS & BIOAVAILABILITY")
add(
 "which magnesium form is best for sleep vs constipation vs general use, and why?",
 "should B vitamins be methylated (methylfolate, methyl-B12), and for whom?",
 "is vitamin D3 clearly better than D2, and does it need K2 and fat to work?",
 "are chelated or glycinate mineral forms actually better absorbed?",
 "does liposomal delivery meaningfully improve absorption (vitamin C, glutathione)?",
 "which supplements must be taken with food and which on an empty stomach?",
 "are 'natural' vitamin forms better than synthetic for any nutrient?",
 "how do I tell a well-dosed supplement from an underdosed proprietary blend?",
)
sec("HABITS & BEHAVIOR CHANGE — making it stick")
add(
 "what does behavior science say actually builds a lasting habit (cue, routine, reward, environment)?",
 "is willpower a limited resource, and how do I design around it?",
 "what is the evidence behind a 'dopamine detox' or dopamine reset?",
 "what are the most effective evidence-based methods to quit compulsive porn or phone use?",
 "how do I use environment design to make good choices automatic?",
 "how long does it really take to form a habit, and what predicts success?",
 "how do I recover from breaking a streak without spiraling?",
 "what builds discipline and consistency more than motivation?",
)
sec("HORMONE OPTIMIZATION & TRT UNDERSTANDING")
add(
 "what daily habits raise natural testosterone the most, ranked by evidence?",
 "when is TRT actually warranted, and what are the real pros, cons, and permanence?",
 "how does natural optimization compare to TRT for a young man with low-normal testosterone?",
 "how do I keep a healthy cortisol rhythm (high morning, low night)?",
 "what is the evidence for DHEA or pregnenolone in young men?",
 "how do I manage estradiol in men — why too low is as bad as too high?",
 "how do finasteride and a GLP-1 affect fertility and sperm, and how do I protect it?",
 "what actually optimizes growth hormone naturally (sleep, fasting, training)?",
)
sec("COST-BENEFIT & PRIORITIZATION — where the money and effort go")
add(
 "if I could only do five things for health, what has the highest return on investment?",
 "which supplements are worth the money and which are wasted spend?",
 "what are the cheapest high-impact interventions for energy, focus, and body composition?",
 "what should I stop doing or stop buying because the evidence doesn't support it?",
 "how do I decide whether a new supplement or protocol is worth adding to my stack?",
)

# ============================ ROUND 15: cravings + parasites/ivermectin ============================
_n15_start = len(qs)
sec("CRAVINGS — sugar & strong food cravings, and how to curb them")
add(
 "what is the most evidence-based way to reduce sugar cravings, and how long do they take to fade?",
 "physiologically, why do intense food cravings happen (dopamine, blood sugar swings, habit, sleep, stress), and which lever matters most?",
 "how do I curb strong food cravings during a calorie deficit without relying on willpower alone?",
 "does cutting sugar make cravings worse before they get better, and how do I get through the adaptation period?",
 "how does short sleep drive sugar and food cravings, and how much does fixing sleep actually reduce them?",
 "how does chronic stress and cortisol drive sugar cravings, and what breaks the stress-eating loop?",
 "how does tirzepatide / GLP-1 reduce food cravings and 'food noise', and what happens to cravings when it's stopped?",
 "how do protein and fiber at a meal blunt later cravings, and what amounts are needed?",
 "how does the porn / scrolling dopamine loop interact with sugar and food cravings?",
 "do artificial sweeteners reduce sugar cravings or make them worse over time?",
 "does a stretch of low-sugar eating reset sweet-taste sensitivity and lower cravings?",
 "which supplements have any real human evidence for reducing sugar cravings (protein, fiber, chromium, berberine, glutamine), and which are hype?",
 "how do ultra-processed, hyper-palatable foods engineer cravings, and does removing them reduce how often cravings hit?",
 "what is the best evidence-based way to respond to a craving in the moment instead of giving in?",
)
sec("PARASITES / DEWORMING / IVERMECTIN — human antiparasitic evidence & safety")
add(
 "what does the human evidence actually say about ivermectin as an antiparasitic, and which infections is it proven to treat?",
 "what is ivermectin's human safety profile, and what are the risks of taking it without a diagnosed parasitic infection?",
 "is routine self-deworming without a confirmed infection supported by any evidence, and what are the downsides?",
 "what are the standard evidence-based antiparasitic drugs for humans (albendazole, mebendazole, praziquantel, nitazoxanide, ivermectin), and what does each treat?",
 "what does the evidence show about mass deworming programs, and does any of it apply to a healthy adult in a developed country?",
 "how would I actually know if I have an intestinal parasite — what symptoms and tests — versus just assuming I do?",
 "how are common human intestinal parasites (giardia, pinworm, tapeworm, hookworm, blastocystis) diagnosed and treated?",
 "how likely is a healthy adult in a developed country to have a parasite, and what raises the risk (travel, undercooked meat, pets)?",
 "do 'parasite cleanse' supplements (wormwood, black walnut, clove) have any real evidence, or are they marketing?",
 "how do parasites and deworming affect the gut microbiome and immune system?",
 "what are the genuine red-flag symptoms that should prompt seeing a doctor for a possible parasitic infection?",
 "when is antiparasitic treatment actually warranted versus unnecessary, and why does treating without a diagnosis carry risk?",
)
sec("ENERGY AVAILABILITY & UNDER-FUELING (RED-S) — the cut + mileage + GLP-1 collision")
add(
 "what is energy availability, how do I estimate it, and what threshold defines low energy availability (LEA)?",
 "am I at real risk of RED-S running a calorie deficit, high mileage, and a GLP-1 that suppresses appetite all at once?",
 "what are the earliest signs of under-fueling and RED-S in a male athlete, and what should I monitor?",
 "how does low energy availability lower testosterone, T3, and bone density, and how fast can it happen?",
 "how do I run a cut and marathon training at the same time without dropping into low energy availability?",
 "how does appetite suppression from tirzepatide raise the risk of accidental under-fueling, and how do I prevent it?",
 "is there a minimum calorie and carbohydrate intake I should not go below while training hard on a cut?",
 "how do I periodize fueling so hard-training days get more carbs and calories than rest days?",
 "can under-fueling actually slow fat loss by suppressing metabolism, hormones, and recovery?",
 "how do I tell healthy fat loss apart from harmful under-fueling using objective markers?",
)
sec("ENDURANCE FUELING & HYDRATION — long runs, sodium, race day")
add(
 "how many grams of carbohydrate per hour are recommended during long runs, and how do I train my gut to tolerate them?",
 "what should I eat before, during, and after a long run for performance and recovery?",
 "how do I estimate my sweat rate and individual sodium needs for long runs and racing?",
 "what causes exercise-associated hyponatremia, and how do I avoid over-drinking on long runs?",
 "does fasted training help or hurt endurance and fat adaptation, and when is it appropriate?",
 "how do carbohydrate needs differ on race day versus easy training days?",
 "how does tirzepatide's slowed gastric emptying affect fueling and GI comfort during runs?",
 "what is carbohydrate periodization / 'train-low', and is it worth doing for a marathoner?",
 "how much protein and carbohydrate should the post-session recovery meal contain, and does timing matter?",
 "how do I choose and test practical race fuels (gels, real food, drink mix) before race day?",
)
sec("IMMUNITY & VACCINES — training load, illness, and staying current")
add(
 "how does heavy endurance training affect immune function, and is the post-long-run 'open window' a real infection risk?",
 "what evidence-based steps reduce getting sick during high training load (sleep, fueling, hygiene, vitamin D, zinc)?",
 "should I train when sick, and what is the 'neck check' rule?",
 "which vaccines should a healthy man in his late 20s be current on?",
 "what is the evidence on the annual flu vaccine for a healthy young adult?",
 "how worthwhile are ongoing COVID boosters for a healthy young adult now?",
 "do intense training or a calorie deficit blunt the immune response to a vaccine?",
 "which immune-support supplements have real evidence versus marketing (vitamin D, zinc, vitamin C, elderberry)?",
 "how does gut health and the microbiome shape immune resilience?",
 "how does chronic sleep loss impair immunity and the response to vaccines?",
)
sec("SLEEP-DISORDERED BREATHING & APNEA — the hidden recovery killer")
add(
 "what are the signs of obstructive sleep apnea, and how would I know if I have it?",
 "how does carrying extra weight raise sleep apnea risk, and does losing weight reverse it?",
 "how do I get screened for sleep apnea (home sleep test versus lab study), and when is it worth doing?",
 "how does untreated sleep apnea affect testosterone, blood pressure, recovery, and cardiovascular risk?",
 "does mouth-taping or positional therapy actually help snoring or mild sleep-disordered breathing, and what's the evidence?",
 "can I have disrupted, unrefreshing sleep from upper-airway resistance without full-blown apnea?",
 "how do alcohol and sedatives worsen sleep-disordered breathing?",
 "what does a wearable's blood-oxygen and breathing data actually tell me about possible sleep apnea?",
)
sec("STARTING A NEW COMPOUND CORRECTLY — the mirror of getting off")
add(
 "what is the correct way to introduce a new supplement or peptide so I can actually tell whether it works?",
 "why add only one new thing at a time, and how long should I trial it before judging?",
 "what should I watch for in the first days and weeks of a new compound (side effects, red flags)?",
 "what baseline bloodwork or measurements should I take before starting a new peptide or hormone-active compound?",
 "how do I titrate a dose upward correctly and find the minimum effective dose?",
 "in what order should I add compounds to a stack to avoid confounding the effects?",
 "how do I set up an objective before/during/after comparison for a new intervention?",
 "when should I abandon a new compound versus give it more time?",
)
sec("MEAL PLANNING — building the plan from scratch")
add(
 "how do I build a meal plan from scratch for a high-protein cut — what steps, in what order?",
 "how do I set my calorie target and macro split for losing fat while keeping muscle at my size and training load?",
 "how much protein per day anchored to goal bodyweight, and how do I distribute it across meals?",
 "how do I structure meals around morning study, a 10-hour workday, and evening training?",
 "how do I hit protein and micronutrients when a GLP-1 has killed my appetite — practical high-density meals?",
 "what does a simple, repeatable batch meal-prep template look like?",
 "how do I build meals that fuel evening training and still support sleep?",
 "which foods give the most protein and nutrients per calorie for a cut, and which should meals be built around?",
 "how do I adjust the meal plan on hard-training days versus rest days?",
 "how do I plan for eating out, travel, and social situations without derailing the cut?",
 "how do I handle food safety and storage for batch-cooked meals (reheating, leftovers, how long they keep)?",
 "how do I keep a meal plan affordable without sacrificing protein or nutrient quality?",
)

# ---- CYCLE PASS: five more sweeps for what we may have forgotten (kept only where evidence is real) ----
sec("CARDIOVASCULAR & CARDIAC SCREENING UNDER LOAD — heart, BP, stimulants, tadalafil")
add(
 "what cardiovascular screening makes sense for a hybrid athlete training hard (resting HR, blood pressure, ECG, later coronary calcium)?",
 "can very high endurance volume cause harmful cardiac changes (athlete's heart, atrial fibrillation, coronary calcium), and at what dose?",
 "how do stimulants like caffeine interact with hard training and heart rhythm — is there a real arrhythmia risk?",
 "how do I monitor and manage blood pressure while cutting, training hard, and using tadalafil?",
 "what resting and recovery heart-rate patterns signal overtraining or a cardiac problem?",
 "when should palpitations, chest symptoms, or unusual breathlessness during training prompt medical evaluation?",
)
sec("RUNNING GI DISTRESS & HEAT — the gut and thermoregulation while running")
add(
 "what causes GI distress and 'runner's trots' during long runs, and how do I prevent it?",
 "how does tirzepatide's delayed gastric emptying compound GI problems during running, and how do I work around it?",
 "how do I acclimatize to heat for hot-weather training and racing, and how long does it take?",
 "how does heat change my fluid, sodium, and pacing needs on long runs?",
 "what are the warning signs of heat illness while running, and how do I avoid it?",
)
sec("OVERTRAINING & MICRONUTRIENT GAPS — total load and low-appetite deficiencies")
add(
 "what is the difference between functional overreaching, non-functional overreaching, and overtraining, and how do I tell which I'm in?",
 "which objective markers (HRV, resting HR, sleep, mood, performance) best detect overtraining early?",
 "with a 10-hour workday plus training plus study, how do I manage total load to avoid burnout and overtraining?",
 "which micronutrient deficiencies become likely when a GLP-1 suppresses how much I eat, and how do I prevent them?",
 "what iron and ferritin problems are common in endurance runners, and how do I catch and fix low iron?",
 "how do I make sure a low-calorie, low-appetite diet still covers magnesium, vitamin D, B12, and electrolytes?",
)
sec("RUNNER BODY MAINTENANCE — skin, feet, chafing at high mileage")
add(
 "how do I prevent blisters, black toenails, and chafing during high-mileage training?",
 "how do I prevent and treat athlete's foot and other skin issues from constant sweaty training?",
 "how should I choose socks and shoes and care for my feet to avoid injuries and skin problems?",
 "what is the evidence-based way to manage delayed-onset muscle soreness after hard or downhill running?",
)
sec("NOISE / HEARING & CAFFEINE — under-queried exposures")
add(
 "how much noise exposure damages hearing, and how do I protect it in a loud work environment?",
 "does noise-induced hearing loss accumulate silently, and what are the early signs to catch?",
 "do loud headphones or earbuds meaningfully damage hearing, and what volume and duration are safe?",
 "how does caffeine tolerance build, and should I cycle or take breaks to keep it effective?",
 "what is the caffeine-timing math to help both a hard session and study without wrecking an early bedtime?",
 "how much caffeine per day is safe, and does it truly improve endurance and focus or mostly offset withdrawal?",
 "does caffeine before evening training hurt my sleep even several hours later?",
)

sec("PARASITE REDUCTION — the CORRECT way, daily use, and does it even help")
add(
 "what is the correct, evidence-based way to reduce or eliminate a parasite if I actually have one — diagnosis first, then targeted treatment?",
 "is taking ivermectin or another antiparasitic every day, or on a routine schedule, supported by any human evidence — or is it harmful?",
 "people online take ivermectin on a fixed 'research' schedule for general health — what does human evidence actually say about that, and what are the risks?",
 "does routine or daily 'parasite cleansing' in a healthy person with no diagnosed infection improve health at all, or is it unnecessary?",
 "what are the real harms of taking antiparasitic drugs long-term or without an infection (liver, neurologic, resistance, microbiome)?",
 "if I suspect a parasite, what is the correct testing and treatment pathway, and when do I need a doctor?",
 "how long should antiparasitic treatment actually last for a real infection, and why isn't it an everyday thing?",
 "do healthy adults in developed countries benefit at all from periodic deworming, based on human data?",
)
sec("DOPAMINE & QUITTING PORN — killing 'bad dopamine', rebuilding drive")
add(
 "how does compulsive porn use dysregulate the dopamine and reward system, and is the change reversible?",
 "what is the evidence-based way to quit porn and restore normal dopamine sensitivity, and how long does recovery take?",
 "what actually is a 'dopamine detox' — what part is real and what is myth?",
 "how do I lower chronic overstimulation ('bad dopamine' from porn, scrolling, junk food) and rebuild drive for hard, meaningful work?",
 "how does quitting porn affect libido, erectile function, focus, and motivation according to human data?",
 "what practical, evidence-based tactics break a compulsive porn or scrolling habit (triggers, environment, replacement behavior)?",
 "does 'dopamine fasting' from high-stimulation inputs actually improve focus and motivation, or is baseline restoration the real mechanism?",
 "how long does the brain's reward sensitivity take to recover after cutting out a compulsive behavior?",
)
sec("HEADPHONES, BLUETOOTH & EMF — hearing and wireless exposure")
add(
 "how loud and how long can I use headphones or earbuds before risking hearing damage, and what's the safe-listening rule?",
 "do Bluetooth wireless earbuds emit meaningful radiation, and does human evidence show any harm?",
 "what does the evidence actually say about radiofrequency EMF from phones and wireless devices and risks like cancer?",
 "is holding a phone to my head or keeping it in my pocket a real EMF concern, or negligible?",
 "does wireless/EMF exposure measurably affect sleep or cognition in controlled human studies?",
 "if I want to be cautious, what evidence-based steps reduce EMF exposure, and do they actually matter?",
 "are wired headphones meaningfully safer than Bluetooth for either hearing or EMF?",
)
sec("MILK & COLOSTRUM — skim/zero-fat vs raw vs bovine colostrum (a distinct idea)")
add(
 "zero-fat/skim milk vs whole vs raw milk — what does human evidence say about which is best for health and for a cut?",
 "is raw (unpasteurized) milk actually more nutritious or beneficial than pasteurized, and what are the real infection risks?",
 "what is bovine colostrum, and what does human evidence show it does for gut health, immunity, and athletic recovery?",
 "is colostrum worth taking for an athlete — leaky gut, respiratory infections, body composition — or is it hype?",
 "does zero-fat milk spike insulin or blunt fat loss compared to whole milk?",
 "how do the protein and bioactives in colostrum compare to whey for recovery and immunity?",
 "which milk or dairy choice best supports a high-protein cut while still getting nutrients?",
 "does raw milk offer any probiotic or enzyme benefit that survives digestion, per the evidence?",
)

# ---- PERSONALIZED A/B/C/D TIERS + SCHEDULE BUILD (capstone; also written to personalized_tiers.txt) ----
_PROF = ("for me — a man in my late 20s, ~230 lb cutting toward ~195 on tirzepatide, hybrid athlete "
         "training for a marathon with speed, morning study, a 10-hour workday Mon-Thu, evening training, "
         "and an early bedtime")
_RUB = ("Grade each into tiers from human evidence: A = would significantly change my life, add it; "
        "B = worth adding, moderate benefit; C = little real change; D = no meaningful change or not supported. "
        "Rank within each tier by evidence strength, and be blunt — put hype in C/D.")
TIER = [
 f"tier common SUPPLEMENTS into A/B/C/D {_PROF}. {_RUB}",
 f"tier PEPTIDE options into A/B/C/D {_PROF}, weighing thin or animal-only evidence honestly. {_RUB}",
 f"tier TRAINING and exercise methods into A/B/C/D {_PROF}. {_RUB}",
 f"tier SLEEP interventions into A/B/C/D {_PROF}. {_RUB}",
 f"tier DIET and nutrition changes into A/B/C/D {_PROF}. {_RUB}",
 f"tier BEHAVIORAL / dopamine changes (quitting porn, cutting scrolling, morning sunlight, etc.) into A/B/C/D {_PROF}. {_RUB}",
 f"tier RECOVERY methods (sauna, cold, massage, deload, sleep) into A/B/C/D {_PROF}. {_RUB}",
 f"tier FAT-LOSS levers for my cut into A/B/C/D {_PROF}. {_RUB}",
 f"tier natural TESTOSTERONE-raising habits into A/B/C/D {_PROF}. {_RUB}",
 f"tier LONGEVITY / healthspan levers into A/B/C/D {_PROF}. {_RUB}",
 f"CAPSTONE — across EVERYTHING (supplements, peptides, training, sleep, diet, behavior, recovery), give me ONE master A/B/C/D tier list of the highest-impact changes {_PROF}, ranked within tiers by human-evidence strength. Only strong human data earns A or B; hype goes to C/D.",
 f"using the A-tier and B-tier changes with the strongest human evidence, BUILD a concrete DAILY schedule for a workday {_PROF} — show exactly when each thing happens from wake to sleep, and why.",
 f"BUILD the WEEKLY structure {_PROF} — training split, long run, recovery, and when each A/B change lands across Mon-Thu work days and Fri-Sun off days.",
 f"for each A-tier change, give the smallest first step and the cue/habit that makes it actually stick in daily life, grounded in behavior-change evidence.",
]
sec("PERSONALIZED A/B/C/D TIERS + SCHEDULE BUILD — the capstone (human data)")
add(*TIER)

_new15 = list(qs[_n15_start:])   # all ROUND-15 sections, headers included

# ============================ ROUND 16: DEEP + real-life applicability ============================
_n16_start = len(qs)

sec("OFF-DAY TRAINING, ACTIVE RECOVERY, WALKING & NEAT")
add(
 "what should I actually do on my off days (Fri–Sun) to recover without losing training adaptations?",
 "how many daily steps should I target for fat loss and heart health, and does walking eat into my running recovery?",
 "active recovery vs complete rest — what does the human evidence say is better for a lifter who also runs?",
 "what is a zone-1 recovery walk, how easy should it be, and how long after a hard session or long run?",
 "should I take a recovery walk the day after my long run, and exactly how long and how easy?",
 "does low-intensity cross-training (easy cycling, swimming, elliptical) on off days speed recovery or just add fatigue?",
 "is a true rest day better fully passive or lightly active for recovery and next-day performance?",
 "how much does NEAT (non-exercise movement) drop during a calorie deficit, and how do I keep it up?",
 "does a 10–15 minute walk after meals meaningfully lower blood sugar, and should I build it into my day?",
 "what off-day mobility or stretching actually improves recovery and running, and what is a waste of time?",
 "how much easy activity on an off day counts as recovery before it becomes junk fatigue that hurts my next hard day?",
 "how do I structure a full active-recovery day — sleep, walking, nutrition, sauna, mobility — concretely?",
 "on a cut with marathon mileage, should off days be complete rest or easy movement to protect energy availability?",
 "does easy walking count toward my cardio and fat-loss goals, or do I need structured runs for that?",
 "what are the signs my 'active recovery' is actually too much and blunting adaptation?",
 "how should I use my two weekend off days differently — one truly off, one active — for a hybrid athlete?",
)

# DEEP per-substance protocol: exact dose, form, timing, food, loading/cycling, time-to-effect
sec("EXACT PROTOCOLS — dose · form · timing · duration (per substance)")
for s,_ in SUBS:
    add(f"for {s}: the exact evidence-based dose, best form, timing (time of day, with or without food), "
        f"any loading or cycling, and how long until effects show — from human studies?")

sec("EXACT PROTOCOLS — key foods and levers")
add(
 "exact daily protein target in grams for me on a cut, how to split it across meals, and the per-meal leucine threshold?",
 "exact carbohydrate grams per hour to take in during long runs, and how to build gut tolerance step by step?",
 "exact caffeine dose and timing before a hard session for performance without wrecking sleep?",
 "exact creatine protocol — load or not, daily grams, timing, and does it matter with carbs?",
 "exact fiber target per day and how to ramp it without GI issues?",
 "exact sodium and fluid intake for my long runs based on sweat rate?",
 "exact vitamin D dose to correct and maintain, and what blood level to target?",
 "exact omega-3 EPA/DHA dose for recovery and the omega-3 index to aim for?",
)

sec("PRACTICAL EXECUTION — real meals, groceries, low-appetite tactics")
add(
 "give me concrete high-protein meals I can actually eat when tirzepatide has killed my appetite?",
 "a realistic weekly grocery list for a high-protein cut at my calorie and protein targets?",
 "exact tactics to hit ~180–195 g protein a day with very low appetite (shakes, density, timing)?",
 "what should each meal look like, with portions, on a training day vs a rest day?",
 "exactly what to eat before, during, and after a long run — foods and amounts?",
 "a simple repeatable weekly meal-prep template that hits my macros?",
 "cheapest high-protein foods per gram of protein, ranked?",
 "what to eat post-lift vs post-run when they fall on different days?",
 "how to build the ideal plate for a cut — proportions of protein, veg, carbs, fat?",
 "grab-and-go options that keep me on protein during a busy 10-hour workday?",
)

sec("DEEP TROUBLESHOOTING — specific scenario → exact fix")
add(
 "I hit the wall late in long runs — the exact fueling and pacing changes to fix it?",
 "my scale weight stalled for two weeks on the cut — the exact diagnostic steps and fix, in order?",
 "I feel flat and weak lifting on a cut plus GLP-1 — exactly what to adjust?",
 "poor sleep despite good habits — the exact troubleshooting order to work through?",
 "afternoon energy crash at work — the exact likely causes and fixes to test?",
 "low morning energy even after 8 hours of sleep — what to check, in order?",
 "GI distress on runs — the exact food and timing changes to try first?",
 "lost motivation to train — the evidence-based exact steps to rebuild it?",
 "a nagging knee or shin from mileage — exact load management and prehab steps?",
 "night-time cravings spike — the exact protocol to shut them down?",
)

sec("EXACT TRAINING NUMBERS — mileage, sets, reps, progression")
add(
 "an exact weekly mileage progression for a first marathon while lifting three days a week?",
 "exact sets, reps, and reps-in-reserve to keep muscle on a cut with three lifting days a week?",
 "how many hard running days per week is the max before recovery suffers on a deficit?",
 "an exact marathon taper — what to cut and when across the final two weeks?",
 "exactly how to lay out 3 runs and 3 lifts across Mon–Sun (long run + easy/interval runs + 3 lifts) to avoid interference?",
 "exact weekly zone-2 volume to build the aerobic base for a marathon at my level?",
 "how many total hard sessions (runs + lifts) per week can I recover from on a calorie deficit?",
 "the exact signs I need a deload and precisely what to reduce when I do?",
 "how to progress lifts (load vs reps) on a cut when strength is hard to add?",
 "how to add speed to marathon training without over-reaching — exact session types and frequency?",
 "with 3 runs and 3 lifts a week (6 training days, 1 rest) on a cut plus a GLP-1, how do I manage recovery so I don't overreach?",
 "is 6 training days a week (3 run + 3 lift) sustainable on a calorie deficit, or does the evidence say to cut a day?",
 "how should I order a 3-lift / 3-run week so leg days don't wreck my runs and the long run stays fresh?",
)

_new16 = list(qs[_n16_start:])   # ROUND-16 deep additions

# dedupe (keep order, keep comments)
seen,out=set(),[]
for q in qs:
    if q.startswith("#"): out.append(q); continue
    k=q.lower()
    if k in seen: continue
    seen.add(k); out.append(q)

hdr=["# HealthCoach — DEEP INTERACTION QUESTION MODEL (auto-generated by build_questions.py)",
     "# Singles + behavior/substance/food x outcome + stacks + higher-order combos + daily structure.",
     "# Run: python3 batch_ask.py interactions.txt   -> logs/coach_log_*.md (Q + A + DOI sources).",
     "# Empty pairs answer honestly ('nothing in the library covers this') instead of inventing.",
     ""]
open("interactions.txt","w").write("\n".join(hdr+out)+"\n")
nq=sum(1 for q in out if not q.startswith("#"))
print("wrote interactions.txt:", nq, "questions +", sum(1 for q in out if q.startswith('#')), "sections")

# also write a focused DELTA of only the round-15 additions, so the new questions can be
# run on their own WITHOUT re-running the full set: python3 batch_ask.py new_cravings_parasites.txt
d_seen,d_out=set(),[]
for q in _new15:
    if q.startswith("#"): d_out.append(q); continue
    k=q.lower()
    if k in d_seen: continue
    d_seen.add(k); d_out.append(q)
# also pull in the NEW matrix entities' auto-crosses (colostrum, EMF/wireless) that the
# generator emits up in the main body — so the delta run answers them too.
_matrix_new = [q for q in out if not q.startswith("#")
               and ("colostrum" in q.lower() or "emf" in q.lower() or "wireless / emf" in q.lower())]
_added_hdr = False
for q in _matrix_new:
    k=q.lower()
    if k in d_seen: continue
    if not _added_hdr:
        d_out.append("# ===== NEW MATRIX CROSSES — colostrum & EMF/wireless (auto-generated) ====="); _added_hdr=True
    d_seen.add(k); d_out.append(q)
dhdr=["# HealthCoach — ROUND 15 delta (NEW questions only): cravings, parasites/ivermectin,",
      "#   energy availability/RED-S, endurance fueling & hydration, immunity & vaccines, sleep apnea,",
      "#   starting a compound, meal planning, cardiac screening, running GI/heat, overtraining &",
      "#   micronutrients, runner body maintenance, noise/hearing & caffeine.",
      "# All are also in interactions.txt. Run just these without repeating the full set:",
      "#   python3 batch_ask.py new_questions_r15.txt   -> logs/coach_log_*.md",
      "# (Supersedes new_cravings_parasites.txt — that older file can be deleted.)",
      ""]
open("new_questions_r15.txt","w").write("\n".join(dhdr+d_out)+"\n")
dnq=sum(1 for q in d_out if not q.startswith("#"))
print("wrote new_questions_r15.txt (delta):", dnq, "new questions")

# ROUND 16 delta — the DEEP, real-life additions (run these on their own, no r15 repeat):
e_seen,e_out=set(),[]
for q in _new16:
    if q.startswith("#"): e_out.append(q); continue
    k=q.lower()
    if k in e_seen: continue
    e_seen.add(k); e_out.append(q)
ehdr=["# HealthCoach — ROUND 16 delta (NEW deep questions only): off-day training / active recovery /",
      "#   walking & NEAT, exact per-substance protocols (dose·form·timing·duration), exact food/lever",
      "#   protocols, practical meals & low-appetite tactics, deep troubleshooting, exact training numbers.",
      "# All are also in interactions.txt. Run just these:",
      "#   python3 batch_ask.py new_questions_r16.txt   -> logs/coach_log_*.md",
      ""]
open("new_questions_r16.txt","w").write("\n".join(ehdr+e_out)+"\n")
enq=sum(1 for q in e_out if not q.startswith("#"))
print("wrote new_questions_r16.txt (delta):", enq, "new deep questions")

# standalone PERSONALIZED tier + schedule file -> its own dedicated log when run alone.
thdr=["# HealthCoach — PERSONALIZED A/B/C/D TIERS + SCHEDULE BUILD (run alone for a clean tier/plan log)",
      "#   A = would significantly change life, add it   B = worth adding, moderate",
      "#   C = little real change   D = no meaningful change / not supported",
      "# Run:  python3 batch_ask.py personalized_tiers.txt   -> logs/coach_log_*.md",
      "# (Also included at the end of interactions.txt and in new_questions_r15.txt.)",
      ""]
open("personalized_tiers.txt","w").write("\n".join(thdr+TIER)+"\n")
print("wrote personalized_tiers.txt:", len(TIER), "tier/schedule questions")
