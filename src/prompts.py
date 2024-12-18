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