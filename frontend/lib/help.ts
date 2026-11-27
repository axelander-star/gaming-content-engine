// Short step-by-step guides for every dashboard page, shown in the help panel
// (question mark in the top bar) and collected on /hilfe. Plain German, no jargon.

export interface HelpGuide {
  /** Route of the page, e.g. "/konten". */
  href: string;
  title: string;
  /** One or two sentences: what the page is for. */
  what: string;
  /** Typical steps on this page, in order. */
  steps: string[];
  /** Things only Alexander can do himself (logins, phone codes, submitting links). */
  yourPart?: string[];
  /** Short hints that save time or avoid mistakes. */
  tips?: string[];
}

export interface StartStep {
  title: string;
  text: string;
  href: string;
  linkLabel: string;
}

/** The "Erste Schritte" flow: from nothing to the first video. */
export const GETTING_STARTED: StartStep[] = [
  {
    title: "Themenbereich anlegen",
    text: "Ein Themenbereich ist ein Thema mit eigenen Kanälen, zum Beispiel „Retro-Spiele“ oder „Uhren“. Gib einen Namen, die Sprachen und ein paar Unterthemen ein.",
    href: "/themenbereiche",
    linkLabel: "Zu den Themenbereichen",
  },
  {
    title: "Kanäle mit dem Kanal-Assistenten vorbereiten",
    text: "Der Assistent sieht, welche Kanäle fehlen, und schlägt Name, Beschreibung, Profilbild und Banner vor. Du legst das Konto auf der Plattform selbst an und bestätigst Telefon und Captcha.",
    href: "/kanal-assistent",
    linkLabel: "Zum Kanal-Assistenten",
  },
  {
    title: "Kanal verbinden",
    text: "Klicke beim Kanal auf „Mit YouTube verbinden“ (oder TikTok, Instagram) und melde dich dort an. Erst dann kann die Engine posten und Zahlen lesen. Dein Passwort sieht die Engine nie.",
    href: "/einstellungen",
    linkLabel: "Zu den Kanälen in den Einstellungen",
  },
  {
    title: "Erstes Video erstellen",
    text: "In der Eigenproduktion wählst du Themenbereich und Thema, lässt ein Skript schreiben und das Video erzeugen. Das fertige Video landet in der Mediathek.",
    href: "/eigenproduktion",
    linkLabel: "Zur Eigenproduktion",
  },
  {
    title: "Prüfen und freigeben",
    text: "Im Freigabecenter siehst du Video, Titel und Text je Kanal. Erst wenn du „Freigeben“ drückst, darf es erscheinen. Wann genau, entscheidet die Engine anhand der Zahlen.",
    href: "/freigabe",
    linkLabel: "Zum Freigabecenter",
  },
];

export const HELP_GUIDES: HelpGuide[] = [
  {
    href: "/",
    title: "Übersicht",
    what: "Die Startseite zeigt auf einen Blick, wie viele Videos in Arbeit sind, was zuletzt erschienen ist und ob irgendwo etwas hakt.",
    steps: [
      "Oben siehst du die wichtigsten Zahlen und den Zustand jeder Plattform.",
      "„Status aller Videos“ zeigt, wo jedes Video gerade steht: Idee, in Arbeit, wartet auf Freigabe, veröffentlicht.",
      "Unter „Fehler“ und „Aktivitäten“ steht, was zuletzt passiert ist.",
    ],
    tips: [
      "Ist alles leer, hast du noch keinen Themenbereich. Starte mit „Erste Schritte“ auf der Hilfe-Seite.",
    ],
  },
  {
    href: "/assistent",
    title: "Assistent",
    what: "Hier sprichst du mit der Engine wie in einem Chat: Plan ändern, Fragen stellen, Bilder oder PDFs zeigen.",
    steps: [
      "Schreib unten in das Feld, was du möchtest, zum Beispiel „Plane nächste Woche zwei Videos zu Uhren“.",
      "Mit der Büroklammer hängst du ein Bild oder PDF an, mit dem Mikrofon sprichst du die Frage ein.",
      "Mit dem Lautsprecher lässt du dir eine Antwort vorlesen.",
    ],
    tips: ["Der Assistent kann nichts veröffentlichen. Freigeben machst du immer im Freigabecenter."],
  },
  {
    href: "/ideen",
    title: "Ideenlabor",
    what: "Ideen für Videos, gefunden in Trends, bei der Konkurrenz und in deinen Recherche-Quellen, jeweils mit Bewertung und Quelle.",
    steps: [
      "Lies die neuesten Ideen durch und schau dir die Bewertung an.",
      "Gute Ideen übernimmst du, dann kommen sie auf den Redaktionsplan.",
      "Unpassende Ideen verwirfst du, damit die Liste übersichtlich bleibt.",
    ],
    tips: ["Eine Idee zu übernehmen startet noch keine Produktion und veröffentlicht nichts."],
  },
  {
    href: "/trend-alarm",
    title: "Trend-Alarm",
    what: "Die Engine beobachtet, welche Themen gerade stark wachsen. Wird ein Thema heiß, schreibt sie eigene Video-Entwürfe und schickt dir einen Alarm aufs Handy.",
    steps: [
      "Neue Alarme erscheinen oben mit Thema und Entwurf.",
      "Passt ein Entwurf, gib ihn mit einem Tipp frei. Sonst einfach ignorieren.",
      "Unter „Vollautomatik je Kanal“ legst du fest, ob ein Kanal heiße Themen ohne Rückfrage bringen darf.",
    ],
    yourPart: ["Für Alarme aufs Handy muss die Push-App einmal eingerichtet sein (siehe Glocke oben)."],
  },
  {
    href: "/redaktionsplan",
    title: "Redaktionsplan",
    what: "Der Kalender: welcher Themenbereich an welchem Tag dran ist, feste Regeln und Feiertage.",
    steps: [
      "Bei einem Tag einen Themenbereich einplanen. Ein Klick auf einen Eintrag ändert ihn.",
      "Unter „Feste Regeln“ legst du Wiederholungen an, zum Beispiel „jeden Donnerstag Uhren“.",
      "Unter „Feiertage und Termine“ trägst du Anlässe ein, zu denen passende Videos kommen sollen.",
    ],
    tips: ["Wie viele Videos pro Tag erscheinen, entscheidet die Engine selbst anhand der Zahlen."],
  },
  {
    href: "/eigenproduktion",
    title: "Eigenproduktion",
    what: "Hier entstehen Videos ganz ohne fremdes Material: Skript, Stimme, eigene Bilder oder Farbflächen und Untertitel.",
    steps: [
      "Unter „Neue Produktion“ Themenbereich und Thema wählen.",
      "„Skript erstellen“ drücken und den Text bei Bedarf anpassen.",
      "Optional die zweite Sprache erstellen lassen (Deutsch oder Englisch).",
      "„Video erzeugen“ drücken. Das fertige Video landet in der Mediathek.",
    ],
    tips: [
      "Unter „Serien“ legst du wiederkehrende Formate an, zum Beispiel „Teil 1, 2, 3“.",
      "Veröffentlicht wird nur, was du im Freigabecenter freigibst.",
    ],
  },
  {
    href: "/mediathek",
    title: "Mediathek",
    what: "Alle deine Videos, Aufnahmen und Bilder, sortiert nach Themenbereich. Das Original bleibt immer unverändert.",
    steps: [
      "Unter „Datei hochladen“ eigene Aufnahmen hinzufügen.",
      "Lange Videos mit „In Shorts zerlegen“ in kurze Clips aufteilen lassen.",
      "Fertige Videos gehen von hier ins Freigabecenter.",
    ],
    tips: ["Von hier aus wird nichts veröffentlicht. Originale werden nach 30 Tagen gelöscht."],
  },
  {
    href: "/freigabe",
    title: "Freigabecenter",
    what: "Hier entscheidest du, was erscheinen darf. Ohne deine Freigabe geht nichts raus.",
    steps: [
      "Ein Video aus der Mediathek wählen und „Beiträge vorbereiten“ oder „Überall vorbereiten“ drücken.",
      "Titel, Beschreibung und Hashtags je Kanal prüfen und bei Bedarf ändern, dann „Texte speichern“.",
      "„Freigeben“ drücken. Die Engine wählt dann den besten Zeitpunkt.",
      "Was nicht passt, mit „Verwerfen“ entfernen. Eine Freigabe kannst du zurückziehen, solange der Beitrag nicht erschienen ist.",
    ],
    yourPart: [
      "TikTok-Beiträge landen als Entwurf in deinem TikTok-Postfach. Dort tippst du in der App einmal auf „Posten“.",
    ],
  },
  {
    href: "/kampagnen",
    title: "Kampagnen",
    what: "Clipping-Kampagnen von Content Rewards: Marken bezahlen für Aufrufe. Die Engine schneidet das Material und schreibt die Texte, du reichst den Link ein.",
    steps: [
      "Auf Content Rewards eine Kampagne öffnen, den ganzen Seitentext kopieren und hier einfügen.",
      "„Formular automatisch ausfüllen“ drücken und „Kampagne anlegen“.",
      "Das Material der Marke mit „Material hochladen“ hinzufügen.",
      "Die Videovorschläge prüfen und freigeben.",
      "Sobald das Video online ist, den Link kopieren, auf Content Rewards einreichen und hier „Eingereicht“ abhaken.",
    ],
    yourPart: [
      "Bei Content Rewards anmelden, deine Kanäle dort verbinden und der Kampagne beitreten.",
      "Den Link binnen 30 Minuten nach Veröffentlichung einreichen. Der Countdown auf der Karte zeigt die Restzeit.",
    ],
  },
  {
    href: "/themenbereiche",
    title: "Themenbereiche",
    what: "Deine Themen, jedes mit eigenen Kanälen und Einstellungen. Es gibt nur, was du selbst anlegst.",
    steps: [
      "Keine Idee? „Themen vorschlagen“ zeigt, was gerade in Deutschland läuft. Bei einem Vorschlag „Übernehmen“ drücken.",
      "Oder „Neuer Themenbereich“ drücken und nur den Namen eintragen. „Von der KI ausfüllen“ ergänzt Unterthemen, Zielgruppe, Tonalität und Beschreibung nach aktuellen Trends. Noch mal drücken gibt einen neuen Vorschlag.",
      "Prüfen und speichern.",
      "Unter „Kanäle nach Themenbereich“ mit „Kanal anlegen“ die Kanäle hinzufügen, oder das dem Kanal-Assistenten überlassen.",
      "Mit „Pausieren“ stoppst du einen Themenbereich, ohne etwas zu löschen.",
    ],
    tips: ["Neue Kanäle starten pausiert und ohne Verbindung. Erst nach dem Verbinden wird etwas gepostet."],
  },
  {
    href: "/konten",
    title: "Konten",
    what: "Alle Kanäle mit Aufrufen, Followern, Einnahmen und einer Empfehlung, welcher Kanal sich am meisten lohnt.",
    steps: [
      "Oben siehst du die Summen der letzten 30 Tage.",
      "„Lohnt sich am meisten“ zeigt die stärksten Kanäle.",
      "In „Alle Konten“ trägst du bei Bedarf Einnahmen von Hand ein („Einnahme speichern“).",
    ],
    tips: ["„Pausieren erwägen“ ist nur ein Vorschlag. Pausiert wird nichts von selbst."],
  },
  {
    href: "/kommentare",
    title: "Kommentare",
    what: "Fragen und Lob beantwortet die Engine selbst. Kritik, heikle Themen und TikTok-Kommentare landen hier mit einem Antwort-Entwurf.",
    steps: [
      "Entwurf lesen, bei Bedarf ändern oder „Neu formulieren“ lassen.",
      "„Antwort senden“ drücken oder „Ignorieren“, wenn keine Antwort nötig ist.",
      "„Jetzt abrufen“ holt neue Kommentare sofort.",
    ],
    yourPart: [
      "TikTok-Kommentare kopierst du selbst hierher („TikTok-Kommentar einfügen“) und die Antwort mit „Antwort kopieren“ zurück in die App.",
    ],
  },
  {
    href: "/kanal-assistent",
    title: "Kanal-Assistent",
    what: "Prüft je Themenbereich, welche Kanäle auf YouTube, TikTok und Instagram fehlen, und bereitet sie fertig vor: Name, Beschreibung, Profilbild, Banner und E-Mail-Adresse.",
    steps: [
      "Beim Themenbereich „fehlende vorbereiten“ drücken.",
      "Die Aufgabe öffnen und „So geht es“ aufklappen. Dort stehen alle Schritte.",
      "„Kanal bei YouTube erstellen“ (oder „Bei TikTok registrieren“) öffnet die Plattform. Werte mit den Kopier-Knöpfen übernehmen, Profilbild und Banner herunterladen und hochladen.",
      "Zurück hier „Kanal ist angelegt“ drücken. Danach geht es direkt zur Anmeldung, damit der Kanal verbunden wird.",
    ],
    yourPart: [
      "Das Konto auf der Plattform selbst anlegen. Telefonnummer, SMS-Code und Captcha bestätigst nur du.",
      "Beim Verbinden mit dem richtigen Konto anmelden und den Zugriff erlauben.",
    ],
    tips: ["Gefällt dir ein Name nicht, drück „Neu recherchieren“ oder „Werte ändern“."],
  },
  {
    href: "/konkurrenz",
    title: "Konkurrenz-Radar",
    what: "Behält YouTube-Kanäle aus deiner Nische im Blick. Läuft dort ein Video ungewöhnlich gut, landet das Thema als Idee im Ideenlabor.",
    steps: [
      "Unter „Beobachtete Kanäle“ einen Kanal eintragen und „Beobachten“ drücken.",
      "„Läuft gerade auffällig gut“ zeigt, was bei der Konkurrenz gerade abhebt.",
    ],
    tips: ["Kopiert wird nichts. Die Engine macht aus dem Thema ein eigenes Video."],
  },
  {
    href: "/linkseiten",
    title: "Linkseiten und Newsletter",
    what: "Jeder Kanal bekommt eine eigene Seite für den Link in der Bio, mit deinen anderen Profilen, neuesten Videos und der Newsletter-Anmeldung.",
    steps: [
      "Bei der Linkseite eines Kanals Text und Links eintragen, speichern und die Seite einschalten.",
      "Unter „Affiliate-Links“ Partner-Links hinzufügen. Sie werden immer mit „Anzeige“ gekennzeichnet.",
      "Unter „Postausgang“ siehst du die Newsletter, die verschickt werden sollen.",
    ],
    yourPart: ["Den Link der Seite trägst du selbst in die Bio deines Profils auf der Plattform ein."],
  },
  {
    href: "/sponsoren",
    title: "Sponsoren-Postfach",
    what: "Füge eine Anfrage einer Marke ein. Die Engine sortiert sie, warnt bei Haken, schlägt einen Preis vor und schreibt eine Antwort.",
    steps: [
      "Die E-Mail der Marke kopieren und unter „Anfrage einfügen“ einfügen.",
      "Warnungen und Preisvorschlag lesen.",
      "Den Antwort-Entwurf kopieren und selbst aus deinem Postfach senden.",
    ],
    yourPart: ["Gesendet wird nichts automatisch. Antworten schickst du selbst."],
  },
  {
    href: "/agenten",
    title: "Agenten",
    what: "Die Helfer der Engine, die im Hintergrund arbeiten, zum Beispiel Trends suchen, Texte schreiben oder Zeitpunkte planen.",
    steps: [
      "In „Alle Agenten“ siehst du, wer gerade läuft und wann zuletzt.",
      "Mit „pausieren“ hältst du einen Helfer an, mit „jetzt ausführen“ startest du ihn sofort.",
      "„Letzte Entscheidungen“ zeigt, was die Helfer entschieden haben und warum.",
    ],
    tips: ["Normalerweise musst du hier nichts tun. Die Seite ist zum Nachschauen da."],
  },
  {
    href: "/rechte",
    title: "Rechte und Lizenzen",
    what: "Fremdes Material wird nur verwendet, wenn die Erlaubnis nachgewiesen ist. Hier hinterlegst du diese Nachweise.",
    steps: [
      "Unter „Lizenzen“ eine Erlaubnis anlegen, zum Beispiel die Freigabe eines Spieleherstellers.",
      "Unter „Material“ siehst du, welches Material freigegeben oder gesperrt ist und warum.",
    ],
    tips: ["Ohne Nachweis bleibt Material gesperrt. Eigenproduktionen brauchen keinen Nachweis."],
  },
  {
    href: "/produktion",
    title: "Videoproduktion",
    what: "Schneidet aus freigegebenem Spielmaterial kurze Hochformat-Clips.",
    steps: [
      "Unter „Gameplay hochladen“ eine Aufnahme hochladen und die passende Lizenz wählen.",
      "Die Engine findet gute Szenen und macht daraus Clips.",
      "Fertige Clips erscheinen unter „Clips“.",
    ],
    tips: ["Bricht der Upload ab, wähl dieselbe Datei erneut. Es geht an der Stelle weiter."],
  },
  {
    href: "/publishing",
    title: "Publishing",
    what: "Zeigt, wie viele Beiträge je Kanal wann erscheinen und warum die Engine so entschieden hat.",
    steps: [
      "Unter „Kanäle“ siehst du die Menge je Kanal und die Begründung.",
      "„Geplante Veröffentlichungen“ zeigt die nächsten Termine.",
    ],
    tips: ["Die Menge legt die Engine selbst anhand von Zahlen, Qualität und Plattformregeln fest."],
  },
  {
    href: "/analytics",
    title: "Analytics",
    what: "Wie gut deine Videos laufen: nach Plattform, Sprache, Spiel, Format, Einstieg und Uhrzeit.",
    steps: [
      "„Stärkste und schwächste Videos“ zeigt, was funktioniert.",
      "„Hook-Tests und Gewinner“ zeigt, welcher Einstieg besser ankommt.",
      "Unter „Wochenbericht per E-Mail“ stellst du den Bericht ein.",
    ],
    tips: ["Erste aussagekräftige Zahlen gibt es nach ein bis zwei Wochen."],
  },
  {
    href: "/kosten",
    title: "Kosten",
    what: "Alle laufenden Kosten: Server, Domain, KI, Speicher und Plattform-Abfragen.",
    steps: [
      "„Fixkosten“ zeigt feste Monatsbeträge.",
      "„Kosten nach Bereich“ zeigt, wofür das Geld ausgegeben wird.",
    ],
    tips: ["Das Monatsbudget stellst du in den Einstellungen ein."],
  },
  {
    href: "/system",
    title: "System",
    what: "Ob alle Teile der Engine laufen, wann zuletzt gesichert wurde und wie ausgelastet der Server ist.",
    steps: [
      "Unter „Prüfungen“ sollte alles grün sein.",
      "„Datensicherung“ zeigt die letzte Sicherung.",
    ],
    tips: ["Bei Problemen kommt zusätzlich eine Meldung über die Glocke oben."],
  },
  {
    href: "/einstellungen",
    title: "Einstellungen",
    what: "Not-Aus, automatisches Veröffentlichen, Budget, Kanäle und Benutzer.",
    steps: [
      "Unter „Kanäle und Sicherheitsgrenzen“ jeden Kanal mit „Mit YouTube verbinden“ (oder TikTok, Instagram) verbinden.",
      "Der Not-Aus stoppt sofort alle Helfer und Veröffentlichungen.",
      "Budget und Obergrenzen je Kanal festlegen.",
    ],
    yourPart: [
      "Beim Verbinden meldest du dich auf der Plattform selbst an und wählst das richtige Konto, zum Beispiel den passenden Brand-Kanal.",
    ],
    tips: ["Obergrenzen sind nur ein Schutz nach oben. Wie viel wirklich erscheint, entscheidet die Engine."],
  },
  {
    href: "/hilfe",
    title: "Hilfe",
    what: "Alle Anleitungen an einem Ort und der Weg zum ersten Video.",
    steps: [
      "Unter „Erste Schritte“ der Reihe nach vorgehen.",
      "Darunter steht für jede Seite eine kurze Anleitung.",
    ],
    tips: ["Auf jeder Seite öffnet das Fragezeichen oben rechts die Anleitung genau für diese Seite."],
  },
];

/** Guide for the given pathname: exact match first, then the longest matching prefix. */
export function guideFor(pathname: string): HelpGuide | undefined {
  const exact = HELP_GUIDES.find((g) => g.href === pathname);
  if (exact) return exact;
  return HELP_GUIDES.filter((g) => g.href !== "/" && pathname.startsWith(g.href + "/")).sort(
    (a, b) => b.href.length - a.href.length,
  )[0];
}
