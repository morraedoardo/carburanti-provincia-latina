# Carburanti · Provincia di Latina

Mappa Streamlit dei prezzi pubblicati nell'open data dell'Osservatorio Prezzi Carburanti del MIMIT.

## Avvio locale

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Pubblicazione su Streamlit Community Cloud

1. Carica `app.py` e `requirements.txt` in un repository GitHub.
2. Accedi a [share.streamlit.io](https://share.streamlit.io/) con GitHub e scegli **Create app**.
3. Seleziona il repository, il branch e `app.py` come file principale.
4. Scegli il sottodominio dell'app e avvia il deploy.

I CSV ufficiali sono salvati nella radice del repository e aggiornati ogni giorno alle 08:30 UTC da GitHub Actions. Il workflow usa il token automatico GitHub `GITHUB_TOKEN`, limitato a questo repository e con il solo permesso di scrivere i contenuti necessari per aggiornare i file. Puoi avviare un aggiornamento anche dalla scheda **Actions** con **Run workflow**. Streamlit legge i dati aggiornati dal repository e non deve collegarsi direttamente al sito MIMIT. I prezzi sono comunicati dai gestori e possono differire da quelli esposti alla pompa; nell'app è indicata la data di comunicazione.

Fonte dati: [MIMIT — Prezzi praticati e anagrafica degli impianti](https://www.mimit.gov.it/it/open-data/elenco-dataset/carburanti-prezzi-praticati-e-anagrafica-degli-impianti).

La visibilità dell'app e del codice dipende dalle impostazioni di condivisione di Streamlit e del repository GitHub. Un repository pubblico rende il codice visibile a chiunque; un'app privata richiede autenticazione per gli utenti invitati.
