"""Which listings are outside the agency's own area: Χαλκιδική, abroad, or elsewhere in Greece.

Thessaloniki agencies also sell holiday homes in Χαλκιδική, islands, Kavala, Attica and
Cyprus, and for Thessaloniki only the city itself counts (suburbs are "Προάστια"). Each
listing gets a `zone` ("Προάστια", "Χαλκιδική", "Εξωτερικό", "Άλλη περιοχή", or None for the
agency's own area). The dashboard hides zoned listings by default; saved searches skip them
unless they set "include_suburbs": true / "include_outside": true.

Only the listing's place and title are read, never the description ("10' from Χαλκιδική").
Names that exist both inside and outside the area (Καλλιθέα, Νέα Μαγνησία, Κηφισιά,
Ηράκλειο, Πεντάλοφος …) are left out: those are only placed by the names around them.
"""
import re

from scraper.common import normalize


def _words(stems, whole=(), raw=()):
    """Stems match the start of a word (κασσανδρ -> Κασσάνδρα, Κασσανδρεία); `whole` the whole word."""
    parts = [re.escape(s) for s in stems] + [re.escape(w) + r"(?!\w)" for w in whole] + list(raw)
    return re.compile(r"(?<!\w)(?:" + "|".join(parts) + ")")


CHALKIDIKI = _words(
    ["χαλκιδικ", "χαλικιδκ", "χαλκδικ", "chalkidik", "halkidik", "kassandr",
     "σιθωνι", "sithoni", "αθως", "athos", "αγιο ορος", "αγ.ορος", "μουδανι", "moudani", "πολυγυρ",
     "poligir", "polygyr", "νικητη", "nikiti", "νεος μαρμαρας", "neos marmaras", "πευκοχωρ", "pefkochor",
     "χανιωτ", "chanioti", "hanioti", "παλιουρ", "paliour", "καλλικρατει", "kallikrat", "σωζοπολ",
     "sozopol", "προποντιδ", "ποτιδαι", "potidai", "φλογητ", "flogit", "νεα πλαγια", "νεα ηρακλεια",
     "τριγλια", "triglia", "παραλια διονυσιου", "dionisiou", "σιβηρ", "sivir", "ποσειδι", "poseidi",
     "φουρκα", "fourka", "κασσανδρει", "αφυτο", "αθυτο", "afito", "κρυοπηγ", "kriopig",
     "πολυχρον", "polichron", "σκιωνη", "skioni", "ελανη", "elani", "μολες καλυβες", "moles kalives",
     "ορμυλι", "ormili", "γερακιν", "geraki", "ψακουδι", "βουρβουρ", "vourvour", "σαρτη", "sarti",
     "τορωνη", "toroni", "πορτο καρρα", "porto carras", "καλαμιτσι", "ορμος παναγιας", "ormos panagias",
     "ουρανουπολ", "ouranoupol", "ιερισσ", "ierissos", "νεα ροδα", "nea roda", "αμμουλιαν", "αμουλιαν",
     "ammoulian", "ολυμπιαδα", "olimpiada", "στρατων", "stratoni", "σταγειρ", "stagir", "ακανθ",
     "akanth", "αρναια", "arnaia", "πυργαδικι", "pyrgadiki", "pirgadiki", "γαλατιστ", "galatist",
     "νεα φωκαια", "nea fokaia", "αγιος μαμας", "καλυβες πολυγυρου", "kalives poligirou", "βατοπεδ",
     "κασσανδριν", "κασανδριν", "kassandrin", "λακκωμα", "λακωμα", "νεα γωνια", "νεα τενεδο",
     "νεα σιλατα", "νεα καλλικρατεια", "μεγαλη παναγια", "παλαιοχωρα χαλκ", "μεταγγιτσ", "βαβδο",
     "αγιος νικολαος σιθων", "συκια χαλκ", "νεα σκιωνη"],
    whole=["παλληνη", "pallini", "code pallini", "συκια", "sikia", "σανη", "sani"],
    raw=[r"κασσ?ανδρ(?!ου)"],  # Κασσάνδρου is a street in Thessaloniki's centre
)
# Ioannina has its own Ολυμπιάδα, Λακκώματα and Παλιουρή: there only the unmistakable names count
CHALKIDIKI_STRONG = _words(["χαλκιδικ", "chalkidik", "halkidik", "kassandr", "σιθωνι", "sithoni", "πευκοχωρ"],
                           whole=["παλληνη", "pallini"], raw=[r"κασσ?ανδρ(?!ου)"])
ABROAD = _words(
    ["κυπρ", "cyprus", "λεμεσ", "limassol", "λευκωσι", "nicosia", "λαρνακ", "larnaca", "αγια ναπα",
     "ayia napa", "λοιπες χωρες", "abroad", "βουλγαρια", "bulgaria", "ισπανι", "spain",
     "ντουμπαι", "dubai", "αλβανι", "albania", "μαυροβουνι", "montenegro", "πορτογαλι", "portugal",
     "ιταλια", "italy", "γερμανια", "germany", "λονδιν", "london", "κροατι", "croatia", "ρουμανι",
     "romania", "istanbul", "κωνσταντινουπολη", "αιγυπτ", "egypt"],
    whole=["παφος", "paphos", "serbia", "τουρκια", "turkey", "usa", "ηπα"],
)
# outside the Thessaloniki prefecture (only applied to Thessaloniki agencies)
OTHER_GREECE = _words(
    ["αττικ", "attica", "attiki", "αθην", "athens", "athina", "πειραι", "piraeus", "piraiki", "καβαλ",
     "kavala", "κυκλαδ", "cyclades", "τζια", "μυκον", "mykonos", "ναξο",
     "σαντοριν", "σεριφ", "serifos", "κρητ", "crete",
     "ηρακλειο κρητ", "heraklion", "ρεθυμν", "rethymn", "λασιθ", "ιεραπετρ", "chios", "λεσβο",
     "μυτιλην", "λημνο", "limnos", "μουδρο", "moudros", "δωδεκανησ", "συμη",
     "ζακυνθ", "κερκυρ", "corfu", "κεφαλονι", "kefaloni", "λευκαδ", "lefkad", "ιθακη", "επτανησ",
     "ionian islands", "ιονιων νησων", "νησοι", "σερρες", "σερρων", "serres", "κιλκις", "kilkis",
     "πιερι", "pieri", "κατεριν", "katerin", "λιτοχωρ", "λεπτοκαρυ", "πλαταμων", "ολυμπιακη ακτη",
     "olimpiaki akti", "ημαθι", "imathia", "βεροι", "veria", "πελλα", "pella", "γιαννιτσ",
     "εδεσσ", "αριδαι", "σκυδρα", "κοζαν", "kozani", "πτολεμαιδ", "φλωριν", "florina", "καστορι",
     "kastoria", "γρεβεν", "grevena", "ξανθη", "κομοτην", "αλεξανδρουπολ", "εβρος", "thasos",
     "κεραμωτ", "keramoti", "ελευθερουπολ", "νεα περαμο", "nea peramos", "νεα ηρακλιτσ", "volos", "πηλιο", "λαρισ", "laris", "τρικαλ", "καρδιτσ", "καλαμπακ", "μετεωρ",
     "meteora", "φθιωτιδ", "ευβοι", "χαλκιδα", "chalkida", "ερετρι", "καρυστο", "βοιωτι",
     "θηβα", "πατρα", "patra", "αχαια", "πελοπον", "πελλοπον", "κορινθ", "corinth", "λουτρακι",
     "loutraki", "ναυπλι", "αργολιδ", "argolis", "καλαματ", "μεσσηνι", "τριπολ", "αρκαδι", "ιωαννιν",
     "ioannina", "πρεβεζ", "ηγουμενιτσ", "παργα", "θεσπρωτι", "thesprot", "αιτωλοακαρναν", "αγρινι",
     "μεσολογγ", "καρπενησ", "στερεα ελλαδα", "κεντρικη ελλαδα", "δυτικη ελλαδα", "σποραδ", "sporades",
     "σκοπελο", "skopelos", "σκιαθο", "αιγινα", "κυθηρα", "kythira", "κερκινη", "σιδηροκαστρ",
     "νιγριτα", "δοιραν", "doiran", "πολυκαστρ", "γουμενισσ", "αμφιπολ", "τσοτυλι", "σιατιστ",
     "αργος ορεστικ", "βεγοριτιδ", "vegoritid", "μεθωνη", "κολινδρ", "πυδνα", "ναουσα", "τυρναβο",
     "γλυφαδ", "αλιμο", "χαλανδρ", "chalandri", "χολαργ", "περιστερι", "κορυδαλλ", "koridall",
     "χαιδαρ", "πεντελη", "εκαλη", "φιλοθεη", "ζωγραφου", "zografou", "παγκρατ", "pagkrati",
     "κυψελη", "kipseli", "μεταξουργει", "metaxourgi", "γκαζι", "λαυρι", "lavrio", "ραφην", "ωρωπο",
     "papagou", "παπαγου", "γερακας", "gerakas", "ανω λιοσια",
     "μεγανησ", "παπιγκ", "θουρια", "πατησιων", "αχαρνων", "αραχοβ", "arachov", "αστρος", "ελαφονησ",
     "γεωργιουπολ", "νεα κυδωνι", "τσοτιλ", "τσοτυλ", "ανατολικος ολυμπος", "κοκκινια", "ζιχνη",
     "κερδυλι", "φιλιπποι", "αγγιστα", "μακρυγιαλ", "οφρυνι", "ofrini", "παλαιο τσιφλικ", "κορινο", "ελευθερες", "eleftheres"],
    whole=["αρτα", "arta", "κεα", "θηρα", "ανδρος", "ανδρου", "παρος", "paros", "βολος", "βολου", "λαμια",
           "θασος", "θασου", "ορφανο", "ορφανου", "orfano", "μηλος", "συρος", "syros", "σαμος", "χιος",
           "ροδος", "βουλα", "σερβια", "κως", "χανια", "chania", "ηλεια", "πυλος", "κρανιδι", "δραμα", "drama",
           "αλεξανδρεια", "alexandreia", "πλατυ", "plati", "υδρα", "ελληνικο", "dion", "νικαια", "nikaia"],
)
# a place name that names its own city wins: "Θεσσαλονίκη, Κηφισιά" is not Athens
HOME = {"Θεσσαλονίκη": _words(["θεσσαλονικ", "thessalonik", "καλαμαρι", "kalamari", "πυλαι", "pylai",
                              "pylea", "θερμη", "thermi", "ευοσμ", "evosm", "πανοραμα"])}


def zone(listing):
    region = listing.get("region") or "Ιωάννινα"
    place = normalize(" | ".join(str(listing.get(k) or "") for k in ("location", "city", "area")))
    title = normalize(listing.get("title") or "")
    home = HOME.get(region)
    at_home = bool(home and home.search(place))
    chalkidiki = CHALKIDIKI if region == "Θεσσαλονίκη" else CHALKIDIKI_STRONG
    checks = [("Χαλκιδική", chalkidiki), ("Εξωτερικό", ABROAD)]
    if region == "Θεσσαλονίκη":
        checks.append(("Άλλη περιοχή", OTHER_GREECE))
    for name, pattern in checks:
        # the place field decides; the title only when the place doesn't name the city itself
        # ("Θέρμη" + "θέα σε Χαλκιδική" stays local; "Θεσσαλονίκη, Κηφισιά" is not Athens)
        if pattern.search(place) and not (name == "Άλλη περιοχή" and at_home):
            return name
        if pattern.search(title) and not at_home:
            return name
    return suburb(listing)


def assign(listings):
    for l in listings:
        l["zone"] = zone(l)


# Thessaloniki: only the city itself (Δήμος Θεσσαλονίκης) counts as the agency's area; the
# suburban municipalities (Καλαμαριά, Πυλαία, Θέρμη, Σταυρούπολη …) get zone "Προάστια".
# Generic words ("Κέντρο", "Αγία Τριάδα", "Άγιος Ιωάννης") are left out: every suburb has one.
SUBURBS = _words(
    ["καλαμαρι", "kalamari", "πυλαι", "pylai", "pylea", "pilea", "θερμη", "thermi", "τhermi", "θερμαικ",
     "thermaik", "πανοραμα", "panorama", "ευοσμ", "evosm", "σταυρουπολ", "stavroupol", "πολιχν", "polichn",
     "polixn", "συκιες", "sykies", "sikies", "νεαπολ", "neapol", "αμπελοκηπ", "ampelokip", "μενεμεν", "menemen",
     "κορδελι", "kordeli", "ευκαρπι", "efkarpi", "pefka", "ωραιοκαστρ",
     "oraiokastr", "oreokastr", "χορτιατ", "chortiat", "ασβεστοχωρ", "asvestochor", "εξοχη", "φιλυρ", "filir",
     "περαι", "perai", "perea", "νεοι επιβατες", "neoi epivates", "επανομ", "επανωμ", "epanom", "μηχανιων",
     "michanion", "τριλοφ", "trilof", "πλαγιαρ", "plagiar", "kardia", "ταγαραδ", "tagarad", "τριαδι", "triadi",
     "νεα ραιδεστ", "nea raidest", "νεο ρυσι", "neo risio", "neo rysio", "vasilika", "σουρωτ", "souroti",
     "μεσημερι", "mesimeri", "σινδο", "sindos", "καλοχωρ", "kalochor", "χαλαστρ", "χαλκηδον", "εχεδωρ",
     "echedor", "διαβατ", "diavata", "νεα μαγνησι", "nea magnisi", "κουφαλι", "λαγκαδ", "lagkad", "ασπροβαλτ",
     "asprovalt", "ρεντιν", "rentin", "ανω σταυρο", "μελισσοχωρ", "melissochor", "μυγδονι", "migdoni",
     "mygdoni", "ζαγκλιβερ", "βερτισκ", "vertisk", "ασσηρ", "assir", "βολβ", "μαδυτ", "νεοχωρουδ", "neochoroud",
     "νεα φιλαδελφει", "δροσια", "drosia", "ανθεμουντ", "anthemount", "καραμπουρνακ", "karampournak",
     "karabournak", "αρετσου", "aretsou", "νεα κρηνη", "nea krini", "βυζαντι", "vizanti", "κωνσταντινοπολιτικ",
     "κωνσταντινουπολιτικ", "konstantinopolitik", "νικοπολ", "nikopol", "επταλοφ",
     "eptalof", "ηλιουπολ", "ζωοδοχου πηγης", "νεα πολιτει", "nea politi", "παυλος μελας", "ευξεινουπολ",
     "δενδροποταμ", "λαχανα", "σχολαρι", "scholari", "αγγελοχωρ", "μονοπηγαδ", "νεα μεσημβρι", "αγχιαλο",
     "καλλινδοι", "αγιος τρυφων", "λουτρα θερμ", "loutra therm", "αεροδρομι", "airport", "βι.πα", "βι. πα",
     "vi.pa", "βιπε", "βι.πε", "περιφ", "suburbs", "προαστι", "west thessaloniki", "east thessaloniki",
     "δυτικη θες", "θδπ", "rest of prefecture", "υπολ. νομου", "περιχωρα", "ανωθεν περιφερειακου",
     "above the ring road", "κολχικ", "μονολοφ", "λητη", "liti", "δρυμο", "σοχο", "sochos", "λακκια", "ροδοχωρ",
     "rodochor", "αρεθουσ", "νεα σαντα", "νεα κερασι", "διονυσος", "απολλωνι", "apolloni", "βρασν", "vrasn",
     "αγιος παυλος", "αγιου παυλου", "agios pavlos", "χιλια δεντρα", "αγιος αθανασιος", "agios athanasios",
     "παλαιοκαστρ", "palaiokastr", "πυλαιωτικ", "pylaiotik", "κατω σχολαρ"],
    whole=["πευκα", "μικρα", "mikra", "καρδια", "βασιλικα", "σταυρος", "δελτα", "καλλιθεα", "kallithea",
           "πενταλοφος", "πενταλοφο", "κρηνη", "κηφισια", "kifisia", "αξιος", "axios", "ηρακλειο", "γαλλικος",
           "ελευθεριο", "eleftherio", "γεφυρα", "σωτηρας", "μεταμορφωση"],
)
CITY = _words(
    ["τουμπα", "toumpa", "toumba", "χαριλαου", "charilaou", "αναληψη", "analipsi", "μποτσαρη", "mpotsari",
     "φαληρο", "faliro", "ιπποκρατει", "ippokrat", "ντεπω", "ntepo", "βουλγαρη", "voulgari", "μαρτιου",
     "martiou", "ανω πολη", "ano poli", "βαρδαρη", "vardari", "λαδαδικα", "ladadika", "ροτοντα", "rotonta",
     "ιστορικο κεντρο", "historical center", "αντιγονιδων", "antigonidon", "αγια σοφια", "agia sofia",
     "διοικητηριο", "dioikitirio", "παπαφη", "papafi", "40 εκκλησιες", "σαραντα εκκλησιες", "40 ekklisies",
     "ευαγγελιστρια", "evaggelistria", "σφαγεια", "ξηροκρηνη", "xirokrini", "παναγια φανερωμενη",
     "panagia faneromeni", "λαχανοκηπ", "lahanokip", "νεα παραλια", "nea paralia", "λευκος πυργος",
     "lefkos pirgos", "σταθμος οσε", "stathmos ose", "τριανδρια", "triandria", "φοινικα", "foinika", "finika",
     "πανεπιστημι", "university", "τουρκικο προξενειο", "τσιναρι", "tsinari",
     "επταπυργι", "γεντι κουλε", "κυριως κεντρο", "υπολοιπο κεντρου", "θεσσαλονικη κεντρο", "κεντρο θεσσαλονικ",
     "center of thessaloniki", "thessaloniki center", "city center", "κεντρικη θεσσαλονικη", "αγιος ελευθεριος",
     "κασσανδρου", "εγνατια", "τσιμισκη", "αριστοτελους", "ναυαριν", "βασ. ολγας", "βασιλισσης ολγας"],
    whole=["δεθ", "καμαρα", "kamara", "depo", "center", "κεντρο"],
)


def suburb(listing):
    """Thessaloniki listings outside the city itself; None where the place is the city or unknown."""
    if (listing.get("region") or "Ιωάννινα") != "Θεσσαλονίκη":
        return None
    place = normalize(" | ".join(str(listing.get(k) or "") for k in ("city", "area")))
    if SUBURBS.search(place):
        return "Προάστια"
    if not CITY.search(place):
        title = normalize(listing.get("title") or "")
        if SUBURBS.search(title) and not CITY.search(title):
            return "Προάστια"
    return None
