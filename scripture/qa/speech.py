"""Make English narration text easy for an English TTS voice to read.

Sanskrit words in IAST (Kṛṣṇa, Bhagavad-gītā, Caitanya) trip up English voices, so words
that carry IAST marks are respelled the way they're commonly said (Krishna, Bhagavad Gita,
Chaitanya). Plain English is left alone.
"""
import re

# Common names first: the generic rules below would give "Krshna" etc.
NAMES = {
    "kṛṣṇa": "Krishna", "kṛṣṇa's": "Krishna's", "bhagavad-gītā": "Bhagavad Gita", "gītā": "Gita",
    # Chosen by ear from samples: "Prubhoo-paada" sounds right with the English voice.
    "prabhupāda": "Prubhoo-paada", "prabhupada": "Prubhoo-paada", "prabhupāda's": "Prubhoo-paada's",
    "prabhupada's": "Prubhoo-paada's", "śrīla": "Shrila", "srila": "Shrila", "śrī": "Shri", "arjuna": "Arjuna",
    "pāṇḍavas": "Pandavas", "pāṇḍu": "Pandu", "dhṛtarāṣṭra": "Dhritarashtra", "sañjaya": "Sanjaya",
    "kurukṣetra": "Kurukshetra", "bhīṣma": "Bhishma", "droṇa": "Drona", "droṇācārya": "Dronacharya",
    "brāhmaṇa": "Brahmana", "kṣatriya": "Kshatriya", "vaiśya": "Vaishya", "śūdra": "Shudra",
    "yoga": "yoga", "karma": "karma", "dharma": "dharma", "ātmā": "atma", "brahman": "Brahman",
    "paramātmā": "Paramatma", "bhakti": "bhakti", "kṛṣṇa-bhakti": "Krishna bhakti",
    "vedas": "Vedas", "veda": "Veda", "upaniṣads": "Upanishads", "vedānta": "Vedanta",
    "caitanya": "Chaitanya", "rādhā": "Radha", "viṣṇu": "Vishnu", "nārāyaṇa": "Narayana",
}
IAST = str.maketrans({
    "ā": "a", "ī": "i", "ū": "u", "ṛ": "ri", "ṝ": "ri", "ḷ": "li", "ṁ": "m", "ṃ": "m", "ḥ": "h",
    "ṅ": "n", "ñ": "n", "ṭ": "t", "ḍ": "d", "ṇ": "n", "ś": "sh", "ṣ": "sh",
    "Ā": "A", "Ī": "I", "Ū": "U", "Ṛ": "Ri", "Ś": "Sh", "Ṣ": "Sh", "Ṭ": "T", "Ḍ": "D", "Ṇ": "N",
})
HAS_IAST = re.compile(r"[āīūṛṝḷṁṃḥṅñṭḍṇśṣĀĪŪṚŚṢṬḌṆ]")


def _word(m: re.Match) -> str:
    w = m.group(0)
    named = NAMES.get(w.lower())
    if named:
        return named if not w[0].isupper() or named[0].isupper() else named.capitalize()
    if not HAS_IAST.search(w):
        return w
    w = re.sub(r"c(?!h)", "ch", w)                 # IAST "c" is said "ch" (ācārya -> acharya)
    w = re.sub(r"C(?!h)", "Ch", w)
    return w.translate(IAST).replace("-", " ")


def english_speech(text: str) -> str:
    t = re.sub(r"[\(\[][^\)\]]*[\)\]]", " ", text)                 # stage directions / refs
    t = re.sub(r"[*_#`~>|\"“”]", "", t)
    t = re.sub(r"[\U0001F000-\U0001FFFF☀-➿️]", "", t)  # emoji
    t = re.sub(r"[\w'āīūṛṝḷṁṃḥṅñṭḍṇśṣĀĪŪṚŚṢṬḌṆ-]+", _word, t)
    return re.sub(r"\s+", " ", t).strip()
