# Medium Article Backend

Backend cloud minimal pour extraire le texte principal d'un article Medium via une API HTTP JSON.

## Ce que fait le backend

Le service expose deux endpoints :

- `GET /api/health` : vérifie que l'API répond.
- `GET /api/extract?url=<URL_MEDIUM>` : valide une URL Medium, récupère l'article via l'API GraphQL Medium, extrait les paragraphes utiles et renvoie du JSON.
- `GET /api/public/extract?url=<URL_MEDIUM>` : endpoint public en lecture seule pour les taches ChatGPT, limite a `medium.com` et `*.medium.com`, sans header `X-API-Key`.
- `GET /api/public/extract/<POST_ID>` : endpoint public en lecture seule qui recoit uniquement un identifiant Medium de 12 caracteres hexadecimaux, sans URL imbriquee ni header `X-API-Key`.

L'URL fournie par le client n'est pas appelée directement comme proxy. Elle sert uniquement à valider le domaine et extraire l'identifiant Medium de l'article. L'appel réseau d'extraction part ensuite vers `https://medium.com/_/graphql`.

## Architecture

```text
medium-backend/
├── app/
│   ├── main.py        # FastAPI endpoints et gestion d'erreurs
│   ├── extractor.py   # Appel GraphQL Medium et extraction texte
│   ├── models.py      # Schemas Pydantic
│   └── security.py    # API key, validation URL, protections SSRF
├── tests/
├── Dockerfile
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

## Prerequis

- Python 3.12+
- Docker, si lancement conteneurise

## Lancement local

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Modifie `.env` localement et choisis une vraie valeur pour `API_KEY`.

```bash
export API_KEY=change-me
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Variables d'environnement

- `API_KEY` : secret attendu dans le header `X-API-Key`.
- `UPSTREAM_TIMEOUT_SECONDS` : timeout de l'appel Medium, par defaut `10`.
- `MAX_RESPONSE_BYTES` : taille maximale de reponse Medium, par defaut `5242880`.
- `PUBLIC_RATE_LIMIT_REQUESTS` : maximum de requetes publiques par fenetre et par IP, par defaut `20`.
- `PUBLIC_RATE_LIMIT_WINDOW_SECONDS` : fenetre du rate limiting public, par defaut `3600`.
- `PUBLIC_MAX_CONTENT_CHARS` : taille maximale du champ `content` renvoye par l'endpoint public, par defaut `200000`.
- `MIN_COMPLETE_WORDS` : seuil indicatif de completude, par defaut `700`.
- `MIN_COMPLETE_PARAGRAPHS` : seuil indicatif de paragraphes, par defaut `5`.
- `LOG_LEVEL` : niveau de logs, par defaut `INFO`.

Ne commit jamais `.env`.

## API

### Health

```bash
curl http://localhost:8000/api/health
```

Reponse :

```json
{
  "status": "ok"
}
```

### Extract

```bash
curl \
  -H "X-API-Key: $API_KEY" \
  "http://localhost:8000/api/extract?url=https://medium.com/data-science-collective/beyond-code-generation-ai-for-the-full-data-science-workflow-ef875dce8453"
```

Exemple de reponse :

```json
{
  "status": "ok",
  "source_url": "https://medium.com/data-science-collective/beyond-code-generation-ai-for-the-full-data-science-workflow-ef875dce8453",
  "title": "Beyond Code Generation: AI for the Full Data Science Workflow",
  "author": "Author name",
  "content": "Full article text...",
  "word_count": 2500,
  "complete": true,
  "warning": null
}
```

Si l'extraction semble incomplete, le service renvoie `status: "partial"` et `complete: false`. Le backend n'invente jamais le contenu manquant.

### Public Extract

```bash
curl \
  "http://localhost:8000/api/public/extract?url=https://medium.com/data-science-collective/beyond-code-generation-ai-for-the-full-data-science-workflow-ef875dce8453"
```

La reponse JSON suit le meme format que `/api/extract`. Cet endpoint ne remplace pas `/api/extract` : il ne demande pas de cle API, mais il est volontairement plus limite.

### Public Extract By Post ID

```bash
curl "http://localhost:8000/api/public/extract/ef875dce8453"
```

Ce chemin utilise directement l'identifiant Medium pour appeler GraphQL. Il refuse les URLs, les segments de chemin, les query strings et les caracteres hors format hexadécimal strict.

## Gestion des erreurs

- `400` : URL invalide ou domaine non autorise.
- `401` : cle API absente ou incorrecte.
- `408` : timeout upstream Medium.
- `413` : reponse upstream trop volumineuse ou contenu public trop volumineux.
- `429` : rate limit public depasse.
- `502` : article inaccessible ou reponse Medium inutilisable.

## Tests

Tests unitaires et API :

```bash
pytest
```

Test d'integration reel avec Medium :

```bash
RUN_REAL_MEDIUM_TEST=1 pytest tests/test_integration_real_medium.py
```

Ce test appelle reellement Medium et peut echouer si Medium change son API, bloque l'hebergeur, ralentit, ou renvoie une reponse partielle.

## Docker

```bash
docker build -t medium-backend .
docker run -p 8000:8000 --env-file .env medium-backend
```

Puis :

```bash
curl http://localhost:8000/api/health
```

## Deploiement

Comparaison rapide :

- Netlify Functions : simple pour fonctions JS/TS, mais moins naturel pour un service Python FastAPI Docker persistant. Possible avec conteneur externe, pas le meilleur choix ici.
- Railway : support Docker simple, variables d'environnement faciles, bon pour petits services HTTP persistants. Demarrage generalement rapide.
- Render : support Docker simple et mature. Le plan gratuit peut s'endormir, ce qui augmente le temps de reponse au premier appel.
- Fly.io : tres bon support Docker, controle fin et service persistant, mais configuration initiale un peu plus technique.

Choix recommande pour cette V1 : Railway, car le backend est un petit service Docker HTTP qui n'a pas besoin de PostgreSQL, Redis, Caddy ni service annexe.

## Credits et licence Freedium

Ce microservice est un projet separe. Il ne modifie pas le depot Freedium original.

La logique d'extraction Medium est adaptee du projet Freedium :

- Projet : https://codeberg.org/Freedium-cfd/web
- Fichiers et concepts consultes : `medium-parser/medium_parser/api.py`, `medium-parser/medium_parser/core.py`, `medium-parser/medium_parser/utils.py`
- Elements repris/adaptes : requete GraphQL `FullPostQuery`, headers compatibles Medium, extraction de l'identifiant d'article depuis l'URL.

Les metadonnees locales de `medium-parser/setup.py` et `freedium-library/pyproject.toml` declarent une licence MIT. Aucun fichier `LICENSE` racine n'etait present dans la copie locale analysee ; avant une redistribution publique importante, verifie la licence canonique du depot amont.

Ce projet est publie sous MIT, avec attribution Freedium pour les parties adaptees.

## Limites connues

- Medium peut modifier son schema GraphQL ou bloquer certains environnements cloud.
- La completude est detectee par heuristiques raisonnables, pas par preuve cryptographique.
- Certains domaines Medium custom peuvent devoir etre ajoutes a `ALLOWED_MEDIUM_HOSTS` pour l'endpoint prive ; l'endpoint public reste limite a `medium.com` et `*.medium.com`.
- Le rate limiting public est en memoire et adapte a un deploiement Railway mono-instance ; il n'est pas partage entre plusieurs replicas et se reinitialise au redemarrage.
- Les embeds, images et markups riches ne sont pas rendus ; l'API renvoie surtout du texte.
- Les articles necessitant une authentification Medium specifique peuvent rester inaccessibles.
