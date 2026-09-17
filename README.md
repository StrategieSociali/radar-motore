# radar-motore

Il codice di una rassegna stampa automatica che gira su routine pianificate di
Claude Code e consegna su Telegram.

- `radar.py` scarica i feed RSS e Atom, tiene le voci recenti, deduplica e
  costruisce la pagina HTML della rassegna.
- `esplodi.py` legge i comandi `numero:tipo` inviati in risposta al recap e
  ricava la notizia a cui si riferiscono.
- `fonti.json` e' l'elenco dei feed.

Solo libreria standard di Python, e `curl` per la rete.

## Perche' questo repository e' pubblico

Le routine leggono pagine web, quindi sono esposte a prompt injection: testo
scritto su una pagina che un modello puo' scambiare per un ordine.

Le routine girano in ambienti cloud dove tutto il traffico verso GitHub passa da
un proxy, fuori dalla sessione, che lascia toccare solo i repository collegati
alla sessione. Le credenziali vere non entrano mai nella sessione.

Questo repository non si collega a nessuna routine: lo clonano dall'indirizzo
pubblico, e per questo non possono scriverci. Anche un agente ingannato da una
pagina non puo' modificare il codice che verra' eseguito il giorno dopo. Se il
repository fosse privato, andrebbe collegato per poterlo leggere, e da quel
momento le routine potrebbero scriverci su un ramo.

Per la stessa ragione qui non ci sono credenziali, dati raccolti, ne' i criteri
con cui i dati vengono filtrati.

## Contributi

Le proposte di modifica esterne non vengono accettate senza essere lette riga
per riga: sono l'unica strada con cui qualcun altro potrebbe cambiare il codice
che le routine eseguono.
