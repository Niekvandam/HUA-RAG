QUERY_REPHRASE_TEMPLATE = """
Herschrijf de vraag voor de zoekopdracht terwijl de betekenis en belangrijke termen intact blijven. 
Zorg ervoor dat de vraag duidelijk en beknopt is, en dat de vraag geen grammaticale fouten bevat.

Gebruikersvraag: {{query}}
Herschreven vraag:
"""


QUERY_ANSWER_TEMPLATE = """
Op basis van de volgende documenten, beantwoord de vraag.
Als je het antwoord niet zeker weet, geef dat dan duidelijk aan.

Documenten:
{% for doc in documents %}
- {{doc}}
{% endfor %}

Vraag: {{query}}
Antwoord:
"""

ANTHROPIC_DEFAULT_PROMPT = """
**Instructies voor het LLM:**

Je bent een expert in het extraheren van metadata uit archiefdocumenten. Je output moet een JSON object zijn dat alle metadata bevat. Alle tekstuele metadata moet in het Nederlands zijn.

**Invoer:**
- **URL:** {{url}}
- **Titel:** {{title}}
- **Beschrijving:** {{beschrijving}}
- **Inhoud:** {{document}}

**Doel:** Genereer een JSON-object met de volgende metadata, afgeleid uit de input:

```json{    "AssetID": "unieke identificatiecode",    "Title": "officiële titel",    "Description": "korte samenvatting van de inhoud",    "PrimaryQuestion": "belangrijkste vraag die het item beantwoordt",    "PrimaryTheme": "hoofdthema van het item",    "SecondaryThemes": ["specifiek subthema 1", "specifiek subthema 2"],    "Entities": ["belangrijke persoon 1", "belangrijke plaats 1", "belangrijk object 1"],    "EntityRelationships": ["beschrijving van relatie 1", "beschrijving van relatie 2"],    "TimePeriod": "historische periode of datum",    "Location": "geografische context",    "AssetType": "type item (Brief, Kaart, Foto, Artikel, etc.)",    "StorylineDimension": "dominante narratieve structuur (Chronologisch, etc.)",    "NarrativeFocus": "hoe het item bijdraagt aan een verhaal",    "URL": "link naar het item",    "Keywords": ["zoekwoord 1", "zoekwoord 2"],    "ExplorationTags": ["thema 1", "thema 2"],    "FollowUpQuestionTags": ["vervolgvraag tag 1", "vervolgvraag tag 2"],    "FullText": "volledige tekst van het item",    "Summary": "korte samenvatting van de volledige tekst",    "Sender": "naam van de afzender (indien van toepassing)",    "Recipient": "naam van de ontvanger (indien van toepassing)",    "DateSent": "datum waarop de brief is verstuurd (indien van toepassing)",    "LetterType": "type brief (Persoonlijk, Officieel, etc.) (indien van toepassing)",    "ContentSummary": "samenvatting van de brief inhoud (indien van toepassing)",    "Scale": "schaal van de kaart (indien van toepassing)",    "MapFeatures": "opvallende kenmerken op de kaart (indien van toepassing)",    "DateCreated": "datum waarop de kaart is gemaakt (indien van toepassing)",    "LocationCovered": "gebieden op de kaart (indien van toepassing)",    "Photographer": "naam van de fotograaf (indien van toepassing)",    "DateTaken": "datum waarop de foto is genomen (indien van toepassing)",    "Event": "gebeurtenis op de foto (indien van toepassing)",    "PeopleInPhoto": "namen van personen op de foto (indien van toepassing)",    "ArticleTopic": "onderwerp van het artikel (indien van toepassing)",    "Author": "naam van de auteur (indien van toepassing)",    "PublicationDate": "datum van publicatie (indien van toepassing)",    "Source": "naam van de tijdschrift/bron (indien van toepassing)"}```

**Instructies:**

1. **Analyseer de "Inhoud":**  Gebruik de inhoud om het `AssetType` te bepalen (Brief, Kaart, Foto, Artikel, etc.).
2. **Metadata Extraheren:** Verzamel alle relevante metadata volgens de velden in het JSON object.
   - Voor een **Brief**: Probeer `Sender`, `Recipient`, `DateSent`, `LetterType` en `ContentSummary` te vinden.
   - Voor een **Kaart**: Probeer `Scale`, `MapFeatures`, `DateCreated` en `LocationCovered` te vinden.
   - Voor een **Foto**: Probeer `Photographer`, `DateTaken`, `Event`, `PeopleInPhoto` en een gedetailleerde `Description` te vinden.
   - Voor een **Artikel**: Probeer `Author`, `PublicationDate`, `Source` en `ArticleTopic` te vinden.
3. **Overkoepelende Metadata:** Vul alle velden van het JSON object in. Gebruik de inhoud, url, titel, en beschrijving en item specifieke metadata voor de overkoepelende metadata.
4. **JSON Output:** Geef de output in het JSON format zoals aangegeven hierboven. De output moet een valide JSON object zijn. Zorg ervoor dat alle strings in het Nederlands zijn. Alle lijsten in het JSON object moeten lijsten van strings zijn.
5. **Taal:** Gebruik correct Nederlands in alle velden. Gebruik het Nederlands dat het meest geschikt is voor archiefmateriaal in Nederland.

**Belangrijke richtlijnen:**

*   Als een veld niet kan worden ingevuld met de gegeven informatie, laat het veld dan leeg, of op `null` (dit is afhankelijk van de openai model die je gebruikt).
*   **Alle textuele uitvoer moet in het Nederlands zijn.**
*   Zorg ervoor dat de output een valide JSON object is.

"""