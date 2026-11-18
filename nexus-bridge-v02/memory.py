"""Bounded, read-only local search in the DOBBY Markdown vault."""
import difflib
import os
import re
import unicodedata
from pathlib import Path

VAULT = Path(__file__).resolve().parent.parent / 'DOBBY'
MAX_FILE = 65536
MAX_FILES = 1000
STOP = set('de du des la le les un une mon ma mes moi je que quel quelle quels quelles comment combien avais utilise utilisee retrouve recette recettes methode pour dans au aux et est par avec version versions'.split())

def normalize(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', value.casefold().replace('œ', 'oe')) if not unicodedata.combining(c))

def tokens(value):
    return [w for w in re.findall(r'[a-z0-9]+', normalize(value)) if len(w) >= 2 and w not in STOP]

class Memory:
    def __init__(self, vault=VAULT):
        self.vault = Path(vault).resolve()

    def _notes(self):
        root = self.vault / 'Cuisine'
        if not root.is_dir() or root.is_symlink() or root.is_junction() or not root.resolve().is_relative_to(self.vault):
            return
        seen = 0
        for base, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = [d for d in dirs if not (Path(base) / d).is_symlink() and not (Path(base) / d).is_junction()]
            for name in sorted(files):
                if not name.lower().endswith('.md'):
                    continue
                seen += 1
                if seen > MAX_FILES:
                    return
                path = Path(base) / name
                try:
                    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()) or path.stat().st_size > MAX_FILE:
                        continue
                    content = path.read_text(encoding='utf-8')
                except (OSError, UnicodeError):
                    continue
                yield path, content

    def search(self, query, limit=4):
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 500 or not isinstance(limit, int) or not 1 <= limit <= 4:
            raise ValueError('invalid_query')
        terms = list(dict.fromkeys(tokens(query)))[:16]
        if not terms:
            return []
        results = []
        for path, content in self._notes() or ():
            # Metadata and sections can match, but only matching lines and headings leave the vault.
            lines = content.splitlines()
            title = path.stem
            name_tokens = tokens(title)
            matched_title = sum(1 for term in terms if term in name_tokens)
            relevant = [line.strip() for line in lines if any(term in tokens(line) for term in terms)]
            score = matched_title * 10 + sum(1 for term in terms if term in tokens(content))
            if not score:
                continue
            excerpt_lines = relevant[:8]
            if matched_title:
                excerpt_lines += [line.strip() for line in lines if line.strip().startswith(('Ingrédients :', 'Quantités :', 'Méthode :', 'Provenance :'))][:4]
            excerpt = '\n'.join(dict.fromkeys(excerpt_lines))[:1200]
            results.append({'source': str(path.relative_to(self.vault)).replace('\\', '/'), 'title': title, 'excerpt': excerpt, '_score': score})
        results.sort(key=lambda item: (-item['_score'], item['source']))
        return [{k: v for k, v in item.items() if k != '_score'} for item in results[:limit]]

    def propose_update(self, relative, proposed):
        if not isinstance(relative, str) or not isinstance(proposed, str) or len(proposed.encode('utf-8')) > MAX_FILE:
            raise ValueError('invalid_proposal')
        matches = [(p, c) for p, c in self._notes() or () if p.relative_to(self.vault).as_posix() == relative]
        if len(matches) != 1:
            raise ValueError('unknown_note')
        _, current = matches[0]
        diff = ''.join(difflib.unified_diff(current.splitlines(keepends=True), proposed.splitlines(keepends=True), fromfile=relative, tofile=relative + ' (proposé)'))
        if len(diff.encode('utf-8')) > MAX_FILE:
            raise ValueError('proposal_too_large')
        return {'source': relative, 'diff': diff, 'applied': False}
