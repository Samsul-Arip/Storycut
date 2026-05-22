from __future__ import annotations

import re
from dataclasses import dataclass


SUPPORTED_SCRIPT_LANGUAGES = {
    "id": "Bahasa Indonesia",
    "en": "English",
}

SUPPORTED_SCRIPT_STYLES = {
    "recap": "Alur Cerita Film",
    "analysis": "Ulasan & Analisis",
    "screenplay": "Skenario/Narasi Rough Cut",
}

SECTION_LABELS = {
    "id": {
        "hook": "Pancingan",
        "setup": "Pembuka",
        "conflict": "Konflik",
        "main_story": "Alur utama",
        "climax": "Klimaks",
        "analysis": "Analisis",
        "closing": "Penutup",
    },
    "en": {
        "hook": "Hook",
        "setup": "Setup",
        "conflict": "Conflict",
        "main_story": "Main story",
        "climax": "Climax",
        "analysis": "Analysis",
        "closing": "Closing",
    },
}


@dataclass(slots=True)
class ScriptSections:
    hook: str
    setup: str
    conflict: str
    main_story: str
    climax: str
    analysis: str
    closing: str

    def render(self, language: str = "id") -> str:
        labels = SECTION_LABELS.get(language, SECTION_LABELS["id"])
        return "\n\n".join(
            [
                f"# {labels['hook']}\n" + self.hook,
                f"# {labels['setup']}\n" + self.setup,
                f"# {labels['conflict']}\n" + self.conflict,
                f"# {labels['main_story']}\n" + self.main_story,
                f"# {labels['climax']}\n" + self.climax,
                f"# {labels['analysis']}\n" + self.analysis,
                f"# {labels['closing']}\n" + self.closing,
            ]
        )


class RuleBasedScriptGenerator:
    """Simple local script drafter. It does not call paid APIs or web services."""

    def generate(
        self,
        transcript_text: str,
        title: str = "this movie",
        language: str = "id",
        style: str = "recap",
    ) -> str:
        clean_text = _normalize_source_text(transcript_text)
        if not clean_text:
            clean_text = (
                "Belum ada transkrip. Import video, extract audio, lalu jalankan "
                "transcription untuk membuat draft yang lebih lengkap."
            )

        if language == "en":
            return self._generate_english(clean_text, title)
        if style == "screenplay":
            return self._generate_indonesian_screenplay(clean_text, title)
        if style == "analysis":
            return self._generate_indonesian_analysis(clean_text, title)
        return self._generate_indonesian_recap(clean_text, title)

    def _generate_indonesian_recap(self, clean_text: str, title: str) -> str:
        sentences = _extract_indonesian_story_sentences(clean_text)
        if not sentences:
            sentences = _extract_readable_story_sentences(clean_text)
        if not sentences:
            return (
                f"Hari ini kita akan membahas alur cerita {title}. "
                "Cerita dimulai ketika para karakter masuk ke sebuah situasi yang perlahan "
                "berubah menjadi konflik besar. Dari sana, setiap keputusan membawa akibat baru "
                "hingga akhirnya cerita mencapai puncak masalah dan memperlihatkan konsekuensi "
                "dari semua pilihan yang sudah terjadi."
            )

        story_sentences = _narrativize_indonesian_story(sentences)
        paragraphs = _sentences_to_paragraphs(story_sentences)
        script = "\n\n".join(paragraphs)
        return _polish_read_aloud_script(script)

    def _generate_indonesian_analysis(self, clean_text: str, title: str) -> str:
        profile = _build_indonesian_profile(clean_text)
        sections = ScriptSections(
            hook=(
                f"Di video ini, kita akan membahas {title} bukan sekadar sebagai rangkaian "
                "adegan, tetapi sebagai cerita tentang pilihan, tekanan, dan konsekuensi. "
                "Bagian menariknya adalah bagaimana momen-momen kecil perlahan mengubah arah "
                "karakter dan membuat konflik terasa semakin penting."
            ),
            setup=_draft_setup_id(title, profile),
            conflict=_draft_conflict_id(profile),
            main_story=_draft_main_story_id(profile),
            climax=_draft_climax_id(profile),
            analysis=_draft_analysis_id(title, profile),
            closing=(
                "Jadi, nilai utama dari cerita ini bukan hanya pada apa yang terjadi, "
                "melainkan pada alasan di balik setiap keputusan dan dampaknya terhadap "
                "karakter. Kalau kalian melihat ceritanya dari sudut pandang itu, film ini "
                "terasa lebih dari sekadar hiburan: ia menjadi bahan untuk memahami tema, "
                "emosi, dan pesan yang ingin disampaikan."
            ),
        )
        return sections.render(language="id")

    def _generate_indonesian_screenplay(self, clean_text: str, title: str) -> str:
        sentences = _extract_indonesian_story_sentences(clean_text)
        if not sentences:
            sentences = _extract_readable_story_sentences(clean_text)
        if not sentences:
            sentences = [
                "Cerita dimulai dari situasi biasa yang berubah ketika konflik utama muncul.",
                "Tokoh utama harus mengejar tujuan penting sambil menghadapi tekanan yang terus membesar.",
                "Pada akhirnya, keputusan terbesar tokoh utama menentukan arah penyelesaian cerita.",
            ]

        story_sentences = _narrativize_indonesian_story(sentences)
        chunks = _split_into_chunks(" ".join(story_sentences), 3)
        setup = _screenplay_excerpt(chunks[0])
        confrontation = _screenplay_excerpt(chunks[1] if len(chunks) > 1 else chunks[0])
        resolution = _screenplay_excerpt(chunks[2] if len(chunks) > 2 else chunks[-1])

        logline = _build_screenplay_logline(title, story_sentences)
        character_profiles = _build_screenplay_character_profiles(story_sentences)
        voiceover_beats = _build_rough_cut_voiceover_beats(story_sentences)

        return "\n\n".join(
            [
                "# PREMIS & LOGLINE\n"
                f"Premis: {logline['premise']}\n"
                f"Logline: {logline['logline']}",
                "# KARAKTERISASI\n" + "\n\n".join(character_profiles),
                "# STRUKTUR TIGA BABAK\n"
                "BABAK 1 - SETUP\n"
                f"{setup}\n\n"
                "BABAK 2 - CONFRONTATION\n"
                f"{confrontation}\n\n"
                "BABAK 3 - RESOLUTION\n"
                f"{resolution}",
                "# NASKAH NARASI ROUGH CUT\n" + "\n\n".join(voiceover_beats),
                "# CATATAN REVISI\n"
                "Revisi pertama: cek apakah setiap bagian sudah terlihat di rough cut dan tidak hanya dijelaskan lewat dialog.\n"
                "Revisi kedua: pendekkan kalimat voice over yang terlalu panjang agar cocok dibaca di atas potongan cepat.\n"
                "Revisi ketiga: pastikan emosi karakter ditunjukkan lewat aksi visual, reaksi, pilihan, dan konsekuensi.",
            ]
        )

    def _generate_english(self, clean_text: str, title: str) -> str:
        chunks = _split_into_chunks(clean_text, 5)
        sections = ScriptSections(
            hook=(
                f"What makes {title} worth talking about is not just what happens, "
                "but how each choice pushes the story into a sharper question."
            ),
            setup=_draft_setup(title, chunks[0]),
            conflict=_draft_conflict(chunks[1] if len(chunks) > 1 else chunks[0]),
            main_story=_draft_main_story(chunks[2] if len(chunks) > 2 else clean_text),
            climax=_draft_climax(chunks[3] if len(chunks) > 3 else chunks[-1]),
            analysis=_draft_analysis(title, chunks[4] if len(chunks) > 4 else chunks[-1]),
            closing=(
                "So the takeaway is not simply whether the movie is good or bad. "
                "The stronger question is what the story reveals about the characters, "
                "the choices they make, and why those choices stay with us after the credits."
            ),
        )
        return sections.render(language="en")


def _split_into_chunks(text: str, chunk_count: int) -> list[str]:
    words = text.split()
    if not words:
        return [""]

    chunk_size = max(1, len(words) // chunk_count)
    chunks = [
        " ".join(words[index : index + chunk_size])
        for index in range(0, len(words), chunk_size)
    ]
    while len(chunks) < chunk_count:
        chunks.append(chunks[-1])
    return chunks[:chunk_count]


def _excerpt(text: str, max_words: int = 90) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + "..."


INDONESIAN_MARKERS = {
    "ada",
    "agar",
    "akan",
    "akhirnya",
    "adalah",
    "alih-alih",
    "anak",
    "atau",
    "bahkan",
    "bahwa",
    "baru",
    "begitu",
    "beliau",
    "berada",
    "bernama",
    "bersama",
    "cerita",
    "dalam",
    "dan",
    "dari",
    "dengan",
    "dia",
    "di",
    "dimana",
    "entah",
    "hal",
    "hingga",
    "ia",
    "ini",
    "itu",
    "jadi",
    "jika",
    "juga",
    "justru",
    "karena",
    "ke",
    "kembali",
    "kemudian",
    "ketika",
    "lalu",
    "mereka",
    "muncul",
    "namun",
    "oleh",
    "pada",
    "para",
    "pun",
    "saat",
    "sang",
    "sampai",
    "sebagai",
    "sebuah",
    "sehingga",
    "sementara",
    "seorang",
    "setelah",
    "sudah",
    "tak",
    "tapi",
    "telah",
    "tempat",
    "tersebut",
    "tidak",
    "untuk",
    "yang",
}

SHORT_NOISE_LINES = {
    "ah",
    "ha",
    "huh",
    "oh",
    "oke",
    "ok",
    "ya",
    "yo",
    "come here",
    "where is it",
    "spanish baby",
    "psychologist",
}

DIALOGUE_MARKERS = {
    "aku",
    "anda",
    "bro",
    "hei",
    "halo",
    "kau",
    "kalian",
    "kami",
    "kamu",
    "kita",
    "ku",
    "saya",
}

INTENT_MARKERS = {
    "berencana",
    "berniat",
    "hendak",
    "harus",
    "ingin",
    "mau",
}

WARNING_MARKERS = {
    "awas",
    "bahaya",
    "berbahaya",
    "hati-hati",
    "jangan",
    "resiko",
    "risiko",
}

CONFLICT_WORDS = {
    "ancaman",
    "balas dendam",
    "dendam",
    "dibunuh",
    "hilang",
    "kematian",
    "konflik",
    "membunuh",
    "menyerang",
    "misteri",
    "musuh",
    "rahasia",
    "tewas",
    "terbunuh",
}

QUESTION_STARTERS = (
    "apa ",
    "apakah ",
    "bagaimana ",
    "bisakah ",
    "di mana ",
    "dimana ",
    "kenapa ",
    "mengapa ",
    "siapa ",
)


def _normalize_source_text(text: str) -> str:
    lines = []
    for raw_line in text.replace("\ufeff", "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _is_timestamp_line(line):
            continue
        line = re.sub(r"\[[^\]]+\]", " ", line)
        line = re.sub(r"\([^\)]+\)", " ", line)
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            continue
        if _is_short_noise(line):
            continue
        lines.append(line)
    return " ".join(lines)


def _extract_indonesian_story_sentences(text: str) -> list[str]:
    parts = _split_sentences(text)
    sentences: list[str] = []
    for part in parts:
        sentence = _clean_sentence(part)
        if not sentence:
            continue
        if not (
            _looks_like_indonesian_story(sentence)
            or _looks_like_dialogue_sentence(sentence)
            or _looks_like_intent(sentence)
            or _looks_like_warning(sentence)
        ):
            continue
        if _is_short_noise(sentence):
            continue
        sentences.append(sentence)
    return _dedupe_neighbors(sentences)


def _extract_readable_story_sentences(text: str) -> list[str]:
    parts = _split_sentences(text)
    sentences: list[str] = []
    for part in parts:
        sentence = _clean_sentence(part)
        if not sentence:
            continue
        if _is_short_noise(sentence):
            continue
        if len(sentence.split()) < 4:
            continue
        sentences.append(sentence)
    return _dedupe_neighbors(sentences)


def _narrativize_indonesian_story(sentences: list[str]) -> list[str]:
    narrative: list[str] = []
    index = 0

    while index < len(sentences):
        current = sentences[index]
        next_sentence = sentences[index + 1] if index + 1 < len(sentences) else ""
        following_sentence = sentences[index + 2] if index + 2 < len(sentences) else ""

        merged = _merge_adjacent_story_beat(current, next_sentence, following_sentence)
        if merged:
            story_sentence, consumed = merged
            narrative.append(_clean_sentence(story_sentence))
            index += consumed
            continue

        story_sentence = _narrativize_single_sentence(current)
        if story_sentence:
            narrative.append(_clean_sentence(story_sentence))
        index += 1

    return _dedupe_neighbors(narrative) or sentences


def _merge_adjacent_story_beat(
    current: str,
    next_sentence: str,
    following_sentence: str,
) -> tuple[str, int] | None:
    if (
        next_sentence
        and _looks_like_scene_setting(current)
        and _looks_like_intent(next_sentence)
    ):
        warning = following_sentence if _looks_like_warning(following_sentence) else ""
        consumed = 3 if warning else 2
        return _compose_intent_beat(current, next_sentence, warning), consumed

    if next_sentence and _looks_like_intent(current) and _looks_like_warning(next_sentence):
        return _compose_intent_beat("", current, next_sentence), 2

    if (
        next_sentence
        and _looks_like_scene_setting(current)
        and _looks_like_warning(next_sentence)
    ):
        return _compose_warning_beat(current, next_sentence), 2

    return None


def _compose_intent_beat(setting: str, intent: str, warning: str = "") -> str:
    context = " ".join(part for part in [setting, intent, warning] if part)
    characters = _infer_story_characters(context)
    intent_phrase = _extract_intent_phrase(intent) or "mengambil keputusan berisiko"

    if setting:
        setting_phrase = _extract_setting_phrase(setting)
        first = (
            f"Di saat {characters['group']} {setting_phrase}, "
            f"{characters['actor']} berniat {intent_phrase}."
        )
    else:
        first = f"{characters['actor_cap']} berniat {intent_phrase}."

    if not warning:
        return first

    warning_phrase = _extract_warning_phrase(warning)
    return f"{first} Namun, {characters['other']} memperingatkan bahwa {warning_phrase}."


def _compose_warning_beat(setting: str, warning: str) -> str:
    characters = _infer_story_characters(setting + " " + warning)
    setting_phrase = _extract_setting_phrase(setting)
    warning_phrase = _extract_warning_phrase(warning)
    return (
        f"Di saat {characters['group']} {setting_phrase}, "
        f"{characters['other']} memperingatkan bahwa {warning_phrase}."
    )


def _narrativize_single_sentence(sentence: str) -> str:
    cleaned = _strip_dialogue_markers(sentence)
    if not cleaned:
        return ""

    if _looks_like_warning(cleaned):
        return f"Karakter lain memperingatkan bahwa {_extract_warning_phrase(cleaned)}."

    if _looks_like_intent(cleaned):
        intent = _extract_intent_phrase(cleaned) or "melakukan sesuatu yang akan mengubah keadaan"
        return f"Salah satu karakter berniat {intent}."

    emotional = _extract_emotional_story_sentence(cleaned)
    if emotional:
        return emotional

    if _looks_like_question(cleaned):
        return (
            "Pertanyaan itu memperlihatkan bahwa karakter tersebut sedang berada "
            "dalam tekanan dan belum sepenuhnya memahami situasi di depannya."
        )

    if _looks_like_dialogue_sentence(cleaned):
        third_person = _lower_first(_third_personize_sentence(cleaned).rstrip(".!?"))
        return f"Momen ini memperlihatkan bahwa {third_person}."

    return _third_personize_sentence(cleaned)


def _extract_emotional_story_sentence(sentence: str) -> str:
    lower = sentence.lower()
    if "apa yang kau tahu" in lower or "apa yang kamu tahu" in lower:
        return (
            "Karakter itu merasa orang lain tidak benar-benar memahami luka "
            "dan masa lalu yang selama ini ia tanggung."
        )
    if "tidak punya orangtua" in lower or "tak punya orangtua" in lower:
        return (
            "Ia digambarkan sebagai sosok yang sejak awal hidup dalam kesendirian, "
            "tanpa keluarga yang bisa menjadi tempatnya bersandar."
        )
    if "kehilangan segalanya" in lower:
        return (
            "Rasa kehilangan menjadi luka terbesar baginya, karena semua hal yang "
            "pernah ia miliki seolah dirampas sekaligus."
        )
    if "ikatan" in lower and ("menderita" in lower or "penderitaan" in lower):
        return (
            "Cerita kemudian menekankan bahwa ikatan antar karakter justru bisa "
            "menjadi sumber penderitaan ketika semuanya berubah menjadi beban."
        )
    return ""


def _infer_story_characters(context: str) -> dict[str, str]:
    lower = context.lower()
    if "kakak" in lower and "adik" in lower:
        return {
            "group": "kakak dan adik",
            "actor": "sang kakak",
            "actor_cap": "Sang kakak",
            "other": "adiknya",
        }
    if "ayah" in lower and "anak" in lower:
        return {
            "group": "sang anak dan ayahnya",
            "actor": "sang anak",
            "actor_cap": "Sang anak",
            "other": "ayahnya",
        }
    if "ibu" in lower and "anak" in lower:
        return {
            "group": "sang anak dan ibunya",
            "actor": "sang anak",
            "actor_cap": "Sang anak",
            "other": "ibunya",
        }
    if "teman" in lower or "sahabat" in lower:
        return {
            "group": "dua karakter itu",
            "actor": "salah satu dari mereka",
            "actor_cap": "Salah satu dari mereka",
            "other": "temannya",
        }
    return {
        "group": "para karakter",
        "actor": "salah satu dari mereka",
        "actor_cap": "Salah satu dari mereka",
        "other": "karakter lain",
    }


def _extract_setting_phrase(sentence: str) -> str:
    lower = _strip_dialogue_markers(sentence).lower()
    lower = _remove_subject_words(lower)
    place = _extract_place_phrase(lower)

    action_phrases = [
        ("duduk", "sedang duduk"),
        ("berjalan", "sedang berjalan"),
        ("berdiri", "sedang berdiri"),
        ("bersembunyi", "sedang bersembunyi"),
        ("bertemu", "sedang bertemu"),
        ("masuk", "mulai masuk"),
        ("melihat", "sedang melihat sesuatu"),
        ("menemukan", "baru menemukan sesuatu"),
    ]
    for marker, phrase in action_phrases:
        if marker in lower:
            return f"{phrase} {place}".strip()

    match = re.search(r"\bsedang\s+(.+)", lower)
    if match:
        phrase = _trim_clause(match.group(0))
        return phrase or "berada dalam situasi itu"

    if place:
        return f"berada {place}"
    return "berada dalam situasi itu"


def _extract_intent_phrase(sentence: str) -> str:
    lower = _strip_dialogue_markers(sentence).lower()
    lower = _remove_subject_words(lower)

    destination = _extract_destination_phrase(lower)
    if destination:
        return f"pergi {destination}"

    match = re.search(
        r"\b(?:mau|ingin|hendak|akan|berniat|berencana|harus)\s+([^,.!?]+)",
        lower,
    )
    if match:
        phrase = _trim_clause(match.group(1))
        if _looks_like_passive_schedule(phrase):
            return ""
        if phrase.startswith("ke "):
            phrase = f"pergi {phrase}"
        return phrase

    match = re.search(r"\b(pergi|menuju|masuk|mencari|menyelamatkan|melawan)\b([^,.!?]*)", lower)
    if match:
        return _trim_clause("".join(match.groups()))

    return ""


def _extract_warning_phrase(sentence: str) -> str:
    lower = _strip_dialogue_markers(sentence).lower()
    lower = lower.replace("disitu", "di situ").replace("disana", "di sana")

    many_match = re.search(r"\bbanyak\s+([^,.!?]+)", lower)
    if many_match:
        danger = _trim_clause(many_match.group(1))
        if danger:
            return f"area itu berbahaya karena ada banyak {danger}"

    reason_match = re.search(r"\b(?:karena|soalnya)\s+([^,.!?]+)", lower)
    if reason_match:
        reason = _trim_clause(reason_match.group(1))
        if reason:
            return reason

    if "bahaya" in lower or "berbahaya" in lower:
        return "tempat itu berbahaya"

    if "jangan" in lower or "awas" in lower or "hati-hati" in lower:
        return "keputusan itu bisa membahayakan mereka"

    return "situasi itu menyimpan bahaya"


def _extract_place_phrase(sentence: str) -> str:
    normalized = sentence.replace("disitu", "di situ").replace("disana", "di sana")
    matches = re.findall(r"\b(di|ke|dari)\s+([^,.!?]+)", normalized)
    if not matches:
        return ""
    preposition, raw_place = matches[-1]
    place = _trim_clause(raw_place)
    if not place:
        return ""
    return f"{preposition} {place}"


def _extract_destination_phrase(sentence: str) -> str:
    normalized = sentence.replace("disitu", "di situ").replace("disana", "di sana")
    match = re.search(
        r"\b(?:mau|ingin|hendak|akan|berniat|berencana|harus)\s+"
        r"(?:pergi\s+)?(ke|menuju)\s+([^,.!?]+)",
        normalized,
    )
    if match:
        preposition, raw_destination = match.groups()
    else:
        travel_match = re.search(r"\bpergi\s+(ke)\s+([^,.!?]+)", normalized)
        if travel_match:
            preposition, raw_destination = travel_match.groups()
        else:
            toward_match = re.search(r"\b(menuju)\s+([^,.!?]+)", normalized)
            if toward_match:
                preposition, raw_destination = toward_match.groups()
            else:
                enter_match = re.search(r"\bmasuk\s+(ke)\s+([^,.!?]+)", normalized)
                if not enter_match:
                    return ""
                preposition, raw_destination = enter_match.groups()

    destination = _trim_clause(raw_destination)
    if not destination:
        return ""
    if preposition == "menuju":
        return f"menuju {destination}"
    return f"ke {destination}"


def _looks_like_scene_setting(sentence: str) -> bool:
    lower = sentence.lower()
    return any(
        marker in lower
        for marker in [
            "berada",
            "bersama",
            "berjalan",
            "bersembunyi",
            "bertemu",
            "berdiri",
            "duduk",
            "masuk",
            "melihat",
            "menemukan",
            "sedang",
        ]
    )


def _looks_like_intent(sentence: str) -> bool:
    lower = sentence.lower()
    if _extract_intent_phrase(sentence):
        return True
    words = set(re.findall(r"[a-zA-Z-]+", lower))
    if words.intersection(INTENT_MARKERS):
        return True
    return any(
        marker in lower
        for marker in [
            "akan pergi",
            "akan menuju",
            "pergi ke",
            "menuju ",
            "mencari ",
            "melawan ",
        ]
    )


def _looks_like_warning(sentence: str) -> bool:
    lower = sentence.lower()
    words = set(re.findall(r"[a-zA-Z-]+", lower))
    return bool(words.intersection(WARNING_MARKERS) or "banyak ular" in lower)


def _looks_like_question(sentence: str) -> bool:
    lower = sentence.lower().lstrip()
    return sentence.strip().endswith("?") or lower.startswith(QUESTION_STARTERS)


def _looks_like_dialogue_sentence(sentence: str) -> bool:
    words = set(re.findall(r"[a-zA-Z-]+", sentence.lower()))
    if words.intersection(DIALOGUE_MARKERS):
        return True
    return _looks_like_question(sentence) or "!" in sentence


def _third_personize_sentence(sentence: str) -> str:
    text = _strip_dialogue_markers(sentence).lower()
    replacements = [
        (r"\baku\b|\bsaya\b", "karakter itu"),
        (r"\bkami\b|\bkita\b", "mereka"),
        (r"\bkamu\b|\bkau\b|\banda\b|\bkalian\b", "karakter lain"),
        (r"\bdiriku\b", "dirinya"),
        (r"\bdirimu\b", "diri karakter lain"),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text)
    text = re.sub(r"\s+", " ", text).strip(" ,.!?")
    if not text:
        return ""
    return text[0].upper() + text[1:] + "."


def _strip_dialogue_markers(sentence: str) -> str:
    text = sentence.replace('"', " ").replace("'", " ")
    text = text.replace("“", " ").replace("”", " ").replace("‘", " ").replace("’", " ")
    text = re.sub(r"\b(?:halo|hei|woi|bro|bang|kak)\b[:,]?\s*", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" \t\r\n-,:;.!?")


def _remove_subject_words(sentence: str) -> str:
    text = re.sub(
        r"\b(?:aku|saya|kami|kita|kau|kamu|kakak|adik|adiknya|sang|dia|ia|mereka)\b",
        " ",
        sentence,
    )
    return re.sub(r"\s+", " ", text).strip()


def _trim_clause(text: str) -> str:
    cleaned = re.split(
        r"\b(?:dan|lalu|namun|tetapi|tapi|karena|seketika|sementara|ketika|saat)\b",
        text,
        maxsplit=1,
    )[0]
    return re.sub(r"\s+", " ", cleaned).strip(" ,.!?")


def _looks_like_passive_schedule(text: str) -> bool:
    lower = text.lower().strip()
    return bool(
        re.match(
            r"\b(?:diadakan|diberikan|dibuat|dilaksanakan|dilakukan|dimulai|"
            r"dipakai|disampaikan|ditentukan)\b",
            lower,
        )
    )


def _lower_first(text: str) -> str:
    if not text:
        return text
    return text[0].lower() + text[1:]


def _split_sentences(text: str) -> list[str]:
    prepared = re.sub(r"\s+", " ", text).strip()
    if not prepared:
        return []
    parts = re.split(r"(?<=[.!?])\s+", prepared)
    if len(parts) <= 1:
        words = prepared.split()
        return [" ".join(words[index : index + 28]) for index in range(0, len(words), 28)]
    return parts


def _clean_sentence(sentence: str) -> str:
    cleaned = sentence.strip(" \t\r\n-")
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"\s+([,.!?])", r"\1", cleaned)
    cleaned = cleaned.replace(" ,", ",").replace(" .", ".")
    if not cleaned:
        return ""
    if cleaned[-1] not in ".!?":
        cleaned += "."
    return cleaned[0].upper() + cleaned[1:]


def _looks_like_indonesian_story(sentence: str) -> bool:
    words = re.findall(r"[A-Za-z']+", sentence.lower())
    if not words:
        return False

    marker_count = sum(1 for word in words if word in INDONESIAN_MARKERS)
    if len(words) <= 3:
        return marker_count > 0
    if marker_count >= 2:
        return True
    if marker_count == 1 and len(words) >= 6:
        return True

    # Keep longer narrative-like Indonesian captions even when auto captions miss punctuation.
    prefixes = ("ber", "ter", "men", "mem", "meng", "meny", "di", "ke", "se", "per")
    prefixed = sum(1 for word in words if word.startswith(prefixes))
    return len(words) >= 8 and prefixed >= 2


def _sentences_to_paragraphs(sentences: list[str], target_words: int = 95) -> list[str]:
    paragraphs: list[str] = []
    current: list[str] = []
    current_words = 0

    for sentence in sentences:
        sentence_words = len(sentence.split())
        if current and current_words + sentence_words > target_words:
            paragraphs.append(" ".join(current))
            current = []
            current_words = 0
        current.append(sentence)
        current_words += sentence_words

    if current:
        paragraphs.append(" ".join(current))
    return paragraphs


def _polish_read_aloud_script(script: str) -> str:
    replacements = {
        " teteleponan": " teleponan",
        " diteleponan": " ditelepon",
        " tidak tahu menau": " tidak tahu-menahu",
        " sekedar ": " sekadar ",
        " kakitangan ": " kaki tangan ",
    }
    polished = script
    for old, new in replacements.items():
        polished = polished.replace(old, new)
    return polished.strip()


def _dedupe_neighbors(sentences: list[str]) -> list[str]:
    deduped: list[str] = []
    previous = ""
    for sentence in sentences:
        fingerprint = re.sub(r"[^a-z0-9]+", "", sentence.lower())
        if fingerprint and fingerprint == previous:
            continue
        deduped.append(sentence)
        previous = fingerprint
    return deduped


def _is_timestamp_line(line: str) -> bool:
    return bool(
        re.match(r"^\d{1,2}:\d{2}(?::\d{2})?(?:[,.]\d+)?(?:\s+-->\s+.+)?$", line)
        or re.match(r"^\d+$", line)
    )


def _is_short_noise(value: str) -> bool:
    normalized = re.sub(r"[^a-zA-Z ]+", "", value).strip().lower()
    if normalized in SHORT_NOISE_LINES:
        return True
    return len(normalized.split()) <= 3 and normalized in SHORT_NOISE_LINES


def _draft_setup(title: str, source: str) -> str:
    return (
        f"At the start of {title}, the story establishes the world, the main pressure, "
        f"and the emotional stakes. Key transcript material to adapt: {_excerpt(source)}"
    )


def _draft_conflict(source: str) -> str:
    return (
        "The conflict begins to sharpen when the characters face a choice they cannot "
        f"easily avoid. Summarize this part in original words and use only short clip support: {_excerpt(source)}"
    )


def _draft_main_story(source: str) -> str:
    return (
        "From there, explain the story progression with commentary between moments. "
        "Focus on cause and effect, character motivation, and your interpretation. "
        f"Transcript material to transform: {_excerpt(source, 120)}"
    )


def _draft_climax(source: str) -> str:
    return (
        "The climax should be framed around the final decision or reveal, then explained "
        f"through your own analysis. Relevant material: {_excerpt(source)}"
    )


def _draft_analysis(title: str, source: str) -> str:
    return (
        f"Use this section to make the review transformative: compare themes, explain "
        f"filmmaking choices, and give a clear point of view about {title}. "
        f"Notes to adapt: {_excerpt(source)}"
    )


def _build_screenplay_logline(title: str, story_sentences: list[str]) -> dict[str, str]:
    first = _screenplay_excerpt(story_sentences[0] if story_sentences else title, 24)
    conflict = _find_representative_sentence(story_sentences, CONFLICT_WORDS) or first
    goal = _find_representative_sentence(story_sentences, INTENT_MARKERS) or conflict
    obstacle = _find_representative_sentence(story_sentences, WARNING_MARKERS) or conflict

    premise = (
        f"{title} mengikuti KARAKTER UTAMA yang terdorong mengejar tujuan penting "
        f"setelah situasi awal berubah: {first}"
    )
    logline = (
        "Ketika konflik utama memaksa KARAKTER UTAMA mengambil keputusan besar, "
        f"ia harus menghadapi rintangan yang semakin menekan: {_lower_first(_screenplay_excerpt(obstacle, 28))} "
        f"Tujuannya menjadi jelas saat {_lower_first(_screenplay_excerpt(goal, 28))}"
    )
    return {"premise": premise, "logline": logline}


def _build_screenplay_character_profiles(story_sentences: list[str]) -> list[str]:
    context = " ".join(story_sentences[:6])
    emotional_hint = _screenplay_excerpt(
        _find_representative_sentence(story_sentences, {"takut", "sendiri", "kehilangan", "luka", "marah"})
        or context,
        30,
    )
    conflict_hint = _screenplay_excerpt(
        _find_representative_sentence(story_sentences, CONFLICT_WORDS | WARNING_MARKERS)
        or context,
        30,
    )

    return [
        "KARAKTER UTAMA (30-an)\n"
        "Latar belakang: sosok yang masuk ke cerita dengan tekanan pribadi yang belum sepenuhnya selesai.\n"
        "Motivasi: ingin mengubah keadaan dan mencapai tujuan yang terasa mendesak.\n"
        f"Kelemahan: mudah terseret emosi ketika situasi mengingatkan pada luka lama, terutama saat {emotional_hint.rstrip('.')}.",
        "TOKOH PENDUKUNG (20-40-an)\n"
        "Latar belakang: orang yang berada dekat dengan konflik dan menjadi cermin bagi keputusan karakter utama.\n"
        "Motivasi: membantu, menahan, atau memperingatkan karakter utama ketika keadaan mulai tidak terkendali.\n"
        "Kelemahan: sering terlambat memahami seberapa besar risiko yang sedang terjadi.",
        "LAWAN/KONFLIK UTAMA (30-50-an)\n"
        "Latar belakang: sumber tekanan yang membuat dunia cerita tidak lagi aman.\n"
        f"Motivasi: mempertahankan kuasa, rahasia, dendam, atau tujuan yang bertabrakan dengan karakter utama saat {conflict_hint.rstrip('.')}.\n"
        "Kelemahan: terlalu yakin bahwa tekanan dan rasa takut cukup untuk mengendalikan keadaan.",
    ]


def _build_rough_cut_voiceover_beats(story_sentences: list[str]) -> list[str]:
    text = " ".join(story_sentences)
    chunks = _split_into_chunks(text, 5)
    labels = [
        ("INT./EXT. DUNIA CERITA - AWAL", "penasaran"),
        ("EXT. LOKASI KONFLIK - BERLANJUT", "menekan"),
        ("INT./EXT. RANGKAIAN ADEGAN - SIANG/MALAM", "cepat"),
        ("EXT. TITIK BALIK - MALAM", "tegang"),
        ("INT./EXT. AKHIR CERITA - MENJELANG SELESAI", "reflektif"),
    ]

    beats: list[str] = []
    for index, (heading, parenthetical) in enumerate(labels):
        source = chunks[index] if index < len(chunks) else chunks[-1]
        action = _screenplay_action_line(source, index)
        vo = _screenplay_voiceover_line(source, index)
        beats.append(
            f"{heading}\n\n"
            f"{action}\n\n"
            "NARATOR (V.O.)\n"
            f"({parenthetical})\n"
            f"{vo}"
        )
    return beats


def _screenplay_action_line(source: str, index: int) -> str:
    excerpt = _screenplay_excerpt(source, 28)
    if index == 0:
        return (
            "KARAKTER UTAMA (30-an) muncul dalam potongan cepat. Kamera menangkap "
            f"situasi awal yang mulai retak: {_lower_first(excerpt)}"
        )
    if index == 1:
        return (
            "Konflik bergerak lebih dekat. Wajah, gerak tubuh, dan reaksi karakter "
            f"menunjukkan tekanan yang tidak bisa lagi diabaikan: {_lower_first(excerpt)}"
        )
    if index == 2:
        return (
            "Montase memperlihatkan rangkaian keputusan dan akibat. Setiap klip pendek "
            f"mendorong cerita maju: {_lower_first(excerpt)}"
        )
    if index == 3:
        return (
            "Ritme potongan semakin intens. Karakter utama tiba di titik balik yang "
            f"memaksanya memilih: {_lower_first(excerpt)}"
        )
    return (
        "Gambar melambat secara emosional. Setelah konflik mencapai puncaknya, cerita "
        f"meninggalkan akibat yang harus dipahami penonton: {_lower_first(excerpt)}"
    )


def _screenplay_voiceover_line(source: str, index: int) -> str:
    excerpt = _screenplay_excerpt(source, 34)
    if index == 0:
        return (
            "Di awal cerita, kita belum langsung diberi jawaban. Yang terlihat justru "
            f"adalah tanda-tanda bahwa hidup karakter utama akan berubah, terutama ketika {_lower_first(excerpt)}"
        )
    if index == 1:
        return (
            "Masalahnya tidak berhenti sebagai kejadian kecil. Konflik ini mulai menekan "
            f"karakter dari berbagai arah, dan bagian pentingnya adalah {_lower_first(excerpt)}"
        )
    if index == 2:
        return (
            "Dari sini, alurnya bergerak sebagai sebab dan akibat. Keputusan yang tampak "
            f"sederhana ternyata membuka masalah baru, apalagi saat {_lower_first(excerpt)}"
        )
    if index == 3:
        return (
            "Inilah titik ketika cerita menuntut keputusan paling besar. Karakter utama "
            f"tidak lagi bisa mundur, karena {_lower_first(excerpt)}"
        )
    return (
        "Pada akhirnya, yang tertinggal bukan hanya siapa menang atau kalah, tetapi apa "
        f"yang berubah dari karakter setelah semua tekanan itu terjadi. Karena itu, {_lower_first(excerpt)}"
    )


def _screenplay_excerpt(text: str, max_words: int = 36) -> str:
    cleaned = _clean_sentence(str(text or ""))
    if not cleaned:
        return "konflik utama mulai mengubah arah cerita"
    words = cleaned.split()
    if len(words) <= max_words:
        return cleaned.rstrip(".") + "."
    return " ".join(words[:max_words]).rstrip(".,;:") + "."


def _find_representative_sentence(sentences: list[str], markers: set[str]) -> str:
    for sentence in sentences:
        lower = sentence.lower()
        if any(marker in lower for marker in markers):
            return sentence
    return ""


def _build_indonesian_profile(text: str) -> dict[str, str | int]:
    word_count = len(text.split())
    sentence_count = max(1, sum(text.count(mark) for mark in ".!?"))

    if word_count < 300:
        density = "singkat"
        pacing = "padat dan langsung ke inti"
    elif word_count < 1500:
        density = "sedang"
        pacing = "seimbang antara rangkuman cerita dan analisis"
    else:
        density = "panjang"
        pacing = "bertahap, dengan pemisahan yang jelas antara alur, klimaks, dan analisis"

    return {
        "word_count": word_count,
        "sentence_count": sentence_count,
        "density": density,
        "pacing": pacing,
    }


def _duration_hint(profile: dict[str, str | int]) -> str:
    word_count = int(profile["word_count"])
    if word_count < 300:
        return "pelan sampai sedang, sekitar dua sampai tiga menit"
    if word_count < 1500:
        return "sedang, sekitar lima sampai delapan menit"
    return "bertahap, sekitar sepuluh menit atau lebih"


def _draft_setup_id(title: str, profile: dict[str, str | int]) -> str:
    return (
        f"Pada bagian awal {title}, jelaskan dulu situasi utama yang membuat cerita ini "
        "bergerak. Perkenalkan dunia cerita, posisi karakter, dan tekanan yang mulai "
        "muncul tanpa membocorkan semuanya terlalu cepat. Karena bahan transkrip proyek "
        f"ini tergolong {profile['density']}, pembukaan sebaiknya dibuat {profile['pacing']}."
    )


def _draft_conflict_id(profile: dict[str, str | int]) -> str:
    return (
        "Setelah penonton memahami situasinya, arahkan narasi ke konflik utama. Jelaskan "
        "apa yang membuat keadaan berubah, mengapa karakter tidak bisa lagi bersikap biasa, "
        "dan pilihan apa yang mulai menekan mereka. Gunakan bagian ini untuk memberi konteks "
        "dengan bahasa sendiri, bukan sekadar mengulang dialog dari video."
    )


def _draft_main_story_id(profile: dict[str, str | int]) -> str:
    return (
        "Masuk ke alur utama, ceritakan perkembangan kejadian sebagai hubungan sebab-akibat. "
        "Setiap momen penting perlu dijelaskan dengan pertanyaan sederhana: apa yang berubah, "
        "siapa yang terdampak, dan kenapa keputusan itu penting untuk cerita. Sisipkan opini "
        "dan interpretasi di antara rangkuman agar video terasa seperti ulasan transformatif, "
        "bukan pengganti film aslinya."
    )


def _draft_climax_id(profile: dict[str, str | int]) -> str:
    return (
        "Saat cerita mencapai klimaks, fokuskan narasi pada keputusan terbesar atau perubahan "
        "paling menentukan. Jelaskan mengapa momen ini menjadi puncak tekanan, bagaimana "
        "karakter merespons, dan apa akibatnya terhadap arah cerita. Bagian ini harus terasa "
        "intens, tetapi tetap disampaikan dengan komentar dan sudut pandang asli."
    )


def _draft_analysis_id(title: str, profile: dict[str, str | int]) -> str:
    return (
        f"Di bagian analisis, bahas kenapa {title} bekerja atau tidak bekerja sebagai cerita. "
        "Sorot tema, perubahan karakter, ritme adegan, konflik moral, atau pilihan penyutradaraan "
        "yang paling terasa. Bagian ini penting karena di sinilah video menjadi karya komentar "
        "dan kritik yang berdiri dengan sudut pandang sendiri."
    )
