import asyncio
import json
import os
import sys
import types
import unittest

import httpx
from archidekt_commander_mcp.schemas.accounts import CollectionLocator

payload = json.load(sys.stdin)
if 'http_base' in payload:
    base_module = types.ModuleType('archidekt_commander_mcp.integrations.http_base')
    base_module.__package__ = 'archidekt_commander_mcp.integrations'
    exec(compile(payload['http_base'], 'http_base.py', 'exec'), base_module.__dict__)
    sys.modules[base_module.__name__] = base_module
module = types.ModuleType('archidekt_commander_mcp.integrations.collection_patch_test')
module.__package__ = 'archidekt_commander_mcp.integrations'
exec(compile(payload['source'], 'public_collection.py', 'exec'), module.__dict__)
Client = module.ArchidektPublicCollectionClient


class CollectionTests(unittest.IsolatedAsyncioTestCase):
    def client(self, handler):
        async def wait():
            pass
        gate = types.SimpleNamespace(wait_for_slot=wait, _sleep=asyncio.sleep)
        settings = types.SimpleNamespace(normalized_archidekt_base_url='https://archidekt.test', archidekt_retry_max_attempts=1)
        return Client(httpx.AsyncClient(transport=httpx.MockTransport(handler)), settings, gate)

    async def snapshot(self, handler, token='fixture-token'):
        client = self.client(handler)
        try:
            return await client.fetch_snapshot(CollectionLocator(collection_id=42), auth_token=token)
        finally:
            await client.http_client.aclose()

    async def test_authenticated_empty_collection(self):
        def handler(request):
            self.assertEqual(request.url.path, '/api/collection/42/v2/')
            self.assertEqual(request.headers['Authorization'], 'JWT fixture-token')
            return httpx.Response(200, json={'count': 0, 'totalPages': 0, 'results': [], 'owner': {'id': 42}})
        snapshot = await self.snapshot(handler)
        self.assertEqual(snapshot.total_records, 0)
        self.assertEqual(snapshot.records, [])
        self.assertEqual(snapshot.owner_id, 42)

    async def test_authenticated_pagination_and_nested_card_fields(self):
        pages = []
        def handler(request):
            page = int(request.url.params['page'])
            pages.append(page)
            card = {'id': 901, 'uid': 'printing-uid', 'rarity': 'rare', 'edition': {'editioncode': 'ABC', 'editionname': 'Test Set'}, 'prices': {'tcg': '2.50'}, 'oracleCard': {'uid': 'oracle-uid', 'name': 'Fixture Card', 'text': 'Test text', 'manaCost': '{1}{B}', 'cmc': 2, 'types': ['Creature'], 'subTypes': ['Test'], 'colors': ['Black'], 'colorIdentity': ['Black'], 'legalities': {'commander': 'Legal'}}}
            return httpx.Response(200, json={'count': 2, 'totalPages': 2, 'results': [{'id': page, 'quantity': page + 1, 'modifier': 'Foil', 'card': card}], 'owner': {'id': 42}})
        snapshot = await self.snapshot(handler)
        self.assertEqual(pages, [1, 2])
        self.assertEqual([r.quantity for r in snapshot.records], [2, 3])
        card = snapshot.records[0]
        self.assertEqual((card.name, card.card_id, card.oracle_id, card.printing_id), ('Fixture Card', 901, 'oracle-uid', 'printing-uid'))
        self.assertEqual((card.mana_cost, card.set_code, card.set_name), ('{1}{B}', 'abc', 'Test Set'))
        self.assertTrue(card.foil)
        self.assertEqual(card.prices['tcg'], 2.5)

    async def test_public_html_read_still_supported(self):
        def handler(request):
            self.assertEqual(request.url.path, '/collection/v2/42')
            self.assertNotIn('Authorization', request.headers)
            props = {'count': 1, 'totalPages': 1, 'redux': {'collectionV2': {'serverCollectionData': [11], 'collectionCards': {'11': {'id': 11, 'quantity': 4, 'card': {'id': 'frontend-generated-id', 'cardId': '901', 'name': 'HTML Card', 'castingCost': ['G']}}}}}}
            return httpx.Response(200, text='<script id="__NEXT_DATA__" type="application/json">' + json.dumps({'props': {'pageProps': props}}) + '</script>')
        snapshot = await self.snapshot(handler, token=None)
        self.assertEqual(snapshot.records[0].name, 'HTML Card')
        self.assertEqual(snapshot.records[0].card_id, 901)
        self.assertEqual(snapshot.records[0].mana_cost, '{G}')

    async def test_auth_failure_is_not_reported_as_empty_collection(self):
        with self.assertRaises(httpx.HTTPStatusError):
            await self.snapshot(lambda request: httpx.Response(401, json={'detail': 'expired'}))

    async def test_invalid_api_payload_is_rejected(self):
        with self.assertRaises(RuntimeError):
            await self.snapshot(lambda request: httpx.Response(200, json={'count': 0}))

    @unittest.skipUnless('http_base' in payload, 'patched http_base fixture not supplied')
    async def test_auth_scheme_is_normalized_by_endpoint(self):
        client = self.client(lambda request: httpx.Response(200))
        previous = os.environ.get('ARCHIDEKT_MCP_AUTH_SCHEME')
        try:
            os.environ['ARCHIDEKT_MCP_AUTH_SCHEME'] = 'jwt'
            v3, _, v3_scheme = client._prepare_request_kwargs(
                'https://archidekt.test/api/decks/v3/?page=1',
                {'headers': {'Authorization': 'JWT fixture-token', 'X-Test': '1'}},
            )
            curated, _, curated_scheme = client._prepare_request_kwargs(
                'https://archidekt.test/api/decks/curated/self/',
                {'headers': {'Authorization': 'Bearer fixture-token'}},
            )
            generic, _, generic_scheme = client._prepare_request_kwargs(
                'https://archidekt.test/api/decks/42/v2/cards/',
                {'headers': {'Authorization': 'Bearer fixture-token'}},
            )
            self.assertEqual(v3['headers']['Authorization'], 'Bearer fixture-token')
            self.assertEqual(v3_scheme, 'Bearer')
            self.assertEqual(curated['headers']['Authorization'], 'JWT fixture-token')
            self.assertEqual(curated_scheme, 'JWT')
            self.assertEqual(generic['headers']['Authorization'], 'JWT fixture-token')
            self.assertEqual(generic_scheme, 'JWT')
            self.assertEqual(v3['headers']['X-Test'], '1')
        finally:
            await client.http_client.aclose()
            if previous is None:
                os.environ.pop('ARCHIDEKT_MCP_AUTH_SCHEME', None)
            else:
                os.environ['ARCHIDEKT_MCP_AUTH_SCHEME'] = previous


unittest.main(argv=['collection-regression'], verbosity=2)
