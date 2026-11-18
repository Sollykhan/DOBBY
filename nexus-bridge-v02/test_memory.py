import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from memory import Memory
from memory_architect import answer

class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        recipes = root / 'Cuisine' / 'Recettes'
        recipes.mkdir(parents=True)
        self.path = recipes / 'Bœuf bourguignon.md'
        self.path.write_text('---\ntype: recette\nversion: v2\ncategorie: plat\ningredients: [carotte]\n---\n# Bœuf bourguignon\nMéthode : mijoter doucement.\n', encoding='utf-8')
        self.memory = Memory(root)

    def test_search_name_ingredient_and_category(self):
        for query in ('boeuf bourguignon', 'carotte', 'plat', 'version v2'):
            result = self.memory.search(query)
            self.assertEqual(result[0]['title'], 'Bœuf bourguignon')
        self.assertEqual(self.memory.search('banane'), [])

    def test_proposal_is_read_only_and_cannot_escape(self):
        before = self.path.read_bytes()
        proposal = self.memory.propose_update('Cuisine/Recettes/Bœuf bourguignon.md', 'nouveau\n')
        self.assertFalse(proposal['applied'])
        self.assertIn('+nouveau', proposal['diff'])
        self.assertEqual(before, self.path.read_bytes())
        with self.assertRaises(ValueError): self.memory.propose_update('../secret.md', 'no')

    def test_search_does_not_follow_external_link(self):
        # Use a separate temporary directory, so the test never overwrites user files.
        with tempfile.TemporaryDirectory() as other:
            external = Path(other) / 'outside.md'
            external.write_text('motuniqueexterieur', encoding='utf-8')
            link = self.path.parent / 'link.md'
            try: link.symlink_to(external)
            except (OSError, NotImplementedError): self.skipTest('symbolic links unavailable')
            self.assertEqual(self.memory.search('motuniqueexterieur'), [])

    def test_architect_mock_receives_only_selected_excerpts(self):
        def fake(key, payload):
            self.assertFalse(payload['store'])
            self.assertNotIn(key, json.dumps(payload))
            self.assertIn('carotte', payload['input'])
            return json.dumps({'status':'completed', 'output':[{'type':'message', 'content':[{'type':'output_text', 'text':json.dumps({'reply':'Fiche Bœuf bourguignon : carotte.'})}]}]}).encode()
        with patch.dict(os.environ, {'OPENAI_API_KEY':'synthetic-key'}):
            self.assertIn('carotte', answer('carotte', self.memory.search('carotte'), transport=fake))
