"""Turn debate text into something a Hindi TTS voice can read aloud.

Hindi voices read Devanagari well but stumble on digits, English letters and symbols,
so: numbers -> Hindi words, acronyms -> spelled out (GST -> जीएसटी), a few common
English words -> Devanagari, and markdown/emojis/stage directions are dropped.
"""
import re

ONES = (
    "शून्य एक दो तीन चार पाँच छह सात आठ नौ दस ग्यारह बारह तेरह चौदह पंद्रह सोलह सत्रह अठारह उन्नीस "
    "बीस इक्कीस बाईस तेईस चौबीस पच्चीस छब्बीस सत्ताईस अट्ठाईस उनतीस तीस इकतीस बत्तीस तैंतीस चौंतीस "
    "पैंतीस छत्तीस सैंतीस अड़तीस उनतालीस चालीस इकतालीस बयालीस तैंतालीस चवालीस पैंतालीस छियालीस "
    "सैंतालीस अड़तालीस उनचास पचास इक्यावन बावन तिरपन चौवन पचपन छप्पन सत्तावन अट्ठावन उनसठ साठ "
    "इकसठ बासठ तिरसठ चौंसठ पैंसठ छियासठ सड़सठ अड़सठ उनहत्तर सत्तर इकहत्तर बहत्तर तिहत्तर चौहत्तर "
    "पचहत्तर छिहत्तर सतहत्तर अठहत्तर उन्यासी अस्सी इक्यासी बयासी तिरासी चौरासी पचासी छियासी सत्तासी "
    "अट्ठासी नवासी नब्बे इक्यानवे बानवे तिरानवे चौरानवे पचानवे छियानवे सत्तानवे अट्ठानवे निन्यानवे"
).split()
assert len(ONES) == 100

LETTERS = {
    "A": "ए", "B": "बी", "C": "सी", "D": "डी", "E": "ई", "F": "एफ़", "G": "जी", "H": "एच",
    "I": "आई", "J": "जे", "K": "के", "L": "एल", "M": "एम", "N": "एन", "O": "ओ", "P": "पी",
    "Q": "क्यू", "R": "आर", "S": "एस", "T": "टी", "U": "यू", "V": "वी", "W": "डब्ल्यू",
    "X": "एक्स", "Y": "वाई", "Z": "ज़ेड",
}

# Common English words the LLM still writes in Latin letters. Extend as you hear mistakes.
WORDS = {
    "dangal": "दंगल", "app": "ऐप", "apps": "ऐप्स", "phone": "फ़ोन", "mobile": "मोबाइल",
    "online": "ऑनलाइन", "offline": "ऑफ़लाइन", "business": "बिज़नेस", "shop": "शॉप",
    "office": "ऑफ़िस", "job": "जॉब", "jobs": "जॉब्स", "internet": "इंटरनेट", "digital": "डिजिटल",
    "tax": "टैक्स", "bank": "बैंक", "petrol": "पेट्रोल", "diesel": "डीज़ल", "train": "ट्रेन",
    "bullet": "बुलेट", "register": "रजिस्टर", "system": "सिस्टम", "development": "डेवलपमेंट",
    "pension": "पेंशन", "scheme": "स्कीम", "budget": "बजट", "debate": "डिबेट", "please": "प्लीज़",
    "sorry": "सॉरी", "ok": "ओके", "okay": "ओके", "thank": "थैंक", "you": "यू", "sir": "सर",
    # character names
    "tiwari": "तिवारी", "imran": "इमरान", "ritika": "रितिका", "rathore": "राठौर",
    "pandit": "पंडित", "bunty": "बंटी", "nephew": "भतीजा", "shaikh": "शेख़", "vinod": "विनोद", "ji": "जी", "bhai": "भाई",
    "madam": "मैडम", "pay": "पे", "payment": "पेमेंट", "youtube": "यूट्यूब", "whatsapp": "व्हाट्सऐप", "live": "लाइव", "news": "न्यूज़",
}


def number_to_hindi(n: int) -> str:
    if n < 100:
        return ONES[n]
    for size, word in ((10**7, "करोड़"), (10**5, "लाख"), (1000, "हज़ार"), (100, "सौ")):
        if n >= size:
            head, rest = divmod(n, size)
            out = f"{number_to_hindi(head)} {word}"
            return f"{out} {number_to_hindi(rest)}" if rest else out
    return str(n)


def _number(match: re.Match) -> str:
    raw = match.group(0).replace(",", "")
    if "." in raw:
        whole, frac = raw.split(".", 1)
        return f"{number_to_hindi(int(whole))} दशमलव " + " ".join(ONES[int(d)] for d in frac)
    return number_to_hindi(int(raw))


def to_speech(text: str) -> str:
    t = text
    # Devanagari digits -> ASCII so one number rule handles both.
    t = t.translate(str.maketrans("०१२३४५६७८९", "0123456789"))
    # Stage directions and formatting.
    t = re.sub(r"[\(\[][^\)\]]*[\)\]]", " ", t)
    t = re.sub(r"[*_#`~>|\"“”‘’]", "", t)
    t = re.sub(r"(?<![A-Za-z])'|'(?![A-Za-z])", "", t)  # quote marks, not apostrophes
    t = re.sub(r"[\U0001F000-\U0001FFFF☀-➿️]", "", t)
    # Symbols with spoken meaning.
    t = re.sub(r"(?:₹|\bRs\.?)\s*([\d,]+(?:\.\d+)?)", r"\1 रुपये", t)
    t = re.sub(r"(\d+)\s*[xX×]\s*(\d+)", r"\1 बाय \2", t)
    t = re.sub(r"(\d)\s*%", r"\1 प्रतिशत", t)
    t = t.replace("&", " और ")
    # Numbers -> words (Indian comma style like 1,00,000 too).
    t = re.sub(r"\d[\d,]*(?:\.\d+)?", _number, t)
    # Acronyms (GST, UPI) -> spelled letters; known English words -> Devanagari.
    t = re.sub(r"\b[A-Z]{2,6}\b", lambda m: "".join(LETTERS[c] for c in m.group(0)), t)
    t = re.sub(r"\b[A-Za-z]+\b", lambda m: WORDS.get(m.group(0).lower(), m.group(0)), t)
    return re.sub(r"\s+", " ", t).strip()
