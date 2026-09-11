#!/usr/bin/env node

import 'dotenv/config';
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { CallToolRequestSchema, ListToolsRequestSchema } from '@modelcontextprotocol/sdk/types.js';
import * as archidekt from './utils/archidekt.js';
import * as scryfall from './utils/scryfall.js';
import { getLegalityIssues, getFormatId, getFormatName } from './utils/legality.js';

const server = new Server(
  {
    name: 'command-tower-mcp',
    version: '0.1.0',
    description: 'Magic: The Gathering deck building tools for Archidekt and Scryfall. For additional research, use web search/fetch to access EDHREC.com (commander staples, synergies), CommanderSpellbook.com (combos), and MTGGoldfish.com (meta, prices).',
  },
  {
    capabilities: {
      tools: {},
      logging: {},
    },
  }
);

server.setRequestHandler(ListToolsRequestSchema, async () => {
  return {
    tools: [
      {
        name: 'create_deck',
        description: 'Create a new deck on Archidekt.',
        inputSchema: {
          type: 'object',
          properties: {
            name: {
              type: 'string',
              description: 'Name for the new deck',
            },
            format: {
              type: 'string',
              description: 'Deck format: commander, standard, modern, legacy, vintage, pauper, "pauper edh" (aka pdh), pioneer, brawl, oathbreaker, "duel commander", premodern, predh, custom',
              default: 'commander',
            },
            description: {
              type: 'string',
              description: 'Optional deck description',
            },
            private: {
              type: 'boolean',
              description: 'Whether the deck should be private (default: true)',
              default: true,
            },
          },
          required: ['name'],
        },
      },
      {
        name: 'list_decks',
        description: 'List all decks in your Archidekt account.',
        inputSchema: {
          type: 'object',
          properties: {},
          required: [],
        },
      },
      {
        name: 'read_deck',
        description: 'Read the contents of an Archidekt deck. Returns a formatted list of card names.',
        inputSchema: {
          type: 'object',
          properties: {
            deck_id: {
              type: 'number',
              description: 'The Archidekt deck ID to read',
            },
          },
          required: ['deck_id'],
        },
      },
      {
        name: 'update_deck',
        description: 'Update cards in an Archidekt deck. Provide cards to add and/or remove as text lists.',
        inputSchema: {
          type: 'object',
          properties: {
            deck_id: {
              type: 'number',
              description: 'The Archidekt deck ID to update',
            },
            cards_to_add: {
              type: 'string',
              description: 'Cards to add. Use # headers for categories, e.g.:\n# Commander\n1 Kenrith, the Returned King\n# Ramp\n1 Sol Ring\n1 Arcane Signet',
            },
            cards_to_remove: {
              type: 'string',
              description: 'Cards to remove, one per line. Format: "2 Sol Ring" or "1x Lightning Bolt".',
            },
          },
          required: ['deck_id'],
        },
      },
      {
        name: 'lookup_cards',
        description: 'Look up Magic: The Gathering cards by name. Returns oracle text, mana cost, type, and other details. Use this to learn about unfamiliar cards.',
        inputSchema: {
          type: 'object',
          properties: {
            card_names: {
              type: 'string',
              description: 'Card names to look up, one per line (max 150)',
            },
          },
          required: ['card_names'],
        },
      },
      {
        name: 'search_cards',
        description: 'Search for Magic: The Gathering cards using Scryfall query syntax. Examples: "ci:simic t:creature cmc<=3" (Simic creatures 3 or less), "o:\\"draw a card\\" c:blue" (blue cards with draw), "otag:ramp ci:green" (green ramp cards), "t:legendary t:creature" (legendary creatures).',
        inputSchema: {
          type: 'object',
          properties: {
            query: {
              type: 'string',
              description: 'Scryfall query string. Common filters: c: (color), ci: (color identity), t: (type), o: (oracle text), otag: (EDHREC tag), cmc: (mana value), pow: (power), tou: (toughness)',
            },
            limit: {
              type: 'number',
              description: 'Maximum number of results to return (default 20, max 175)',
            },
            page: {
              type: 'number',
              description: 'Page number for paginated results (default 1)',
            },
            order: {
              type: 'string',
              description: 'Sort order: name, released (by date), edhrec (by popularity), cmc, color, rarity, power, toughness (default: name)',
            },
            include_text: {
              type: 'boolean',
              description: 'Include oracle text in results (default false)',
            },
            format: {
              type: 'string',
              description: 'Filter to cards legal in format: commander (default), modern, legacy, standard, pioneer, pauper, paupercommander (Pauper EDH), vintage, etc. Use "all" for no filter. Tip for Pauper EDH: "format:paupercommander" gives 99-legal (common) cards; add "r:uncommon t:creature" to find eligible commanders.',
            },
          },
          required: ['query'],
        },
      },
    ],
  };
});

// Legality checking and format-name/ID handling live in ./utils/legality.js
// (getLegalityIssues, getFormatId, getFormatName), imported above.

// Whether a deck text list contains any card lines below its category headers.
function hasCardLines(text) {
  return text.split('\n').some((l) => {
    const t = l.trim();
    return t && !t.startsWith('#');
  });
}

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  // create_deck
  if (name === 'create_deck') {
    try {
      const { accessToken, rootFolder } = await archidekt.getAuth();
      server.sendLoggingMessage({ level: 'info', data: `Creating deck: ${args.name}` });

      const deck = await archidekt.createDeck(accessToken, {
        name: args.name,
        parentFolder: rootFolder,
        deckFormat: getFormatId(args.format),
        description: args.description || '',
        private: args.private !== false,
      });

      return {
        content: [{
          type: 'text',
          text: `Created deck "${deck.name}" (ID: ${deck.id})\nURL: https://archidekt.com/decks/${deck.id}`,
        }],
      };
    } catch (error) {
      server.sendLoggingMessage({ level: 'error', data: `Create deck error: ${error.message}` });
      return {
        content: [{ type: 'text', text: `Failed to create deck: ${error.message}` }],
        isError: true,
      };
    }
  }

  // list_decks
  if (name === 'list_decks') {
    try {
      const { accessToken } = await archidekt.getAuth();
      server.sendLoggingMessage({ level: 'info', data: 'Fetching deck list...' });

      const decks = await archidekt.listDecks(accessToken);

      if (!decks || decks.length === 0) {
        return {
          content: [{ type: 'text', text: 'No decks found.' }],
        };
      }

      // Fetch details for each deck to get commander and description
      const deckPreviews = await Promise.all(
        decks.map(async (d) => {
          try {
            const deck = await archidekt.getDeck(accessToken, d.id);
            const format = getFormatName(deck.deckFormat);
            const privacy = deck.private ? '(private)' : '(public)';

            // Extract color identity from deck colors
            const colorOrder = ['W', 'U', 'B', 'R', 'G'];
            const colors = d.colors || {};
            const colorId = colorOrder.filter(c => colors[c] > 0).join('') || 'C';

            // Find commanders (cards in "Commander" category)
            const commanders = (deck.cards || [])
              .filter(c => c.categories?.includes('Commander'))
              .map(c => c.card.oracleCard.name);

            // Build preview
            const cardCount = (deck.cards || []).reduce((sum, c) => sum + (c.quantity || 1), 0);
            let preview = `**${deck.name}** (ID: ${d.id}) - ${colorId} ${format} ${privacy} [${cardCount} cards]`;
            if (commanders.length > 0) {
              preview += `\n  Commander: ${commanders.join(' & ')}`;
            }
            if (deck.description) {
              let desc = deck.description;
              // Parse Quill Delta format if present
              try {
                const parsed = JSON.parse(desc);
                if (parsed.ops && Array.isArray(parsed.ops)) {
                  desc = parsed.ops
                    .map(op => (typeof op.insert === 'string' ? op.insert : ''))
                    .join('')
                    .trim();
                }
              } catch {
                // Not JSON, use as-is
              }
              if (desc) {
                desc = desc.length > 500 ? desc.slice(0, 500) + '...' : desc;
                preview += `\n  Description: ${desc}`;
              }
            }
            return preview;
          } catch {
            // Fallback if deck details fail
            const format = getFormatName(d.deckFormat);
            const privacy = d.private ? '(private)' : '(public)';
            const colorOrder = ['W', 'U', 'B', 'R', 'G'];
            const colors = d.colors || {};
            const colorId = colorOrder.filter(c => colors[c] > 0).join('') || 'C';
            return `**${d.name}** (ID: ${d.id}) - ${colorId} ${format} ${privacy}`;
          }
        })
      );

      return {
        content: [{
          type: 'text',
          text: `Found ${decks.length} deck(s):\n\n${deckPreviews.join('\n\n')}`,
        }],
      };
    } catch (error) {
      server.sendLoggingMessage({ level: 'error', data: `List decks error: ${error.message}` });
      return {
        content: [{ type: 'text', text: `Failed to list decks: ${error.message}` }],
        isError: true,
      };
    }
  }

  // read_deck
  if (name === 'read_deck') {
    try {
      const { accessToken } = await archidekt.getAuth();
      server.sendLoggingMessage({ level: 'info', data: `Reading deck ${args.deck_id}...` });

      const deck = await archidekt.getDeck(accessToken, args.deck_id);
      const cards = deck.cards || [];

      if (cards.length === 0) {
        return {
          content: [{ type: 'text', text: `Deck "${deck.name}" is empty.` }],
        };
      }

      const entries = cards.map(c => ({
        name: c.card.oracleCard.name,
        qty: c.quantity,
        category: c.categories?.[0] || 'Uncategorized',
      }));

      // Group entries by category
      const byCategory = {};
      for (const e of entries) {
        if (!byCategory[e.category]) byCategory[e.category] = [];
        byCategory[e.category].push(e);
      }

      // Calculate total card count
      const totalCards = entries.reduce((sum, e) => sum + e.qty, 0);

      // Format output
      let output = `# ${deck.name} — ${getFormatName(deck.deckFormat)} (${totalCards} cards)\n\n`;
      for (const [category, categoryCards] of Object.entries(byCategory)) {
        const categoryCount = categoryCards.reduce((sum, e) => sum + e.qty, 0);
        output += `# ${category} (${categoryCount})\n`;
        for (const e of categoryCards) {
          output += `${e.qty}x ${e.name}\n`;
        }
        output += '\n';
      }

      output += `Total: ${totalCards} cards\n\n`;

      const issues = getLegalityIssues(cards, deck.deckFormat);

      output += `# Legality — ${getFormatName(deck.deckFormat)}\n`;
      if (issues.length === 0) {
        output += `No legality issues found.\n`;
      } else {
        output += `${issues.length} issue(s):\n`;
        for (const issue of issues) {
          output += `- ${issue}\n`;
        }
      }

      return {
        content: [{ type: 'text', text: output.trim() }],
      };
    } catch (error) {
      server.sendLoggingMessage({ level: 'error', data: `Read deck error: ${error.message}` });
      return {
        content: [{ type: 'text', text: `Failed to read deck: ${error.message}` }],
        isError: true,
      };
    }
  }

  // update_deck
  if (name === 'update_deck') {
    const { deck_id, cards_to_add, cards_to_remove } = args;

    if (!cards_to_add && !cards_to_remove) {
      return {
        content: [{ type: 'text', text: 'Please provide cards_to_add and/or cards_to_remove.' }],
        isError: true,
      };
    }

    try {
      const { accessToken } = await archidekt.getAuth();
      server.sendLoggingMessage({ level: 'info', data: `Fetching deck ${deck_id}...` });

      // Get current deck state
      const deck = await archidekt.getDeck(accessToken, deck_id);
      const issuesBefore = new Set(getLegalityIssues(deck.cards || [], deck.deckFormat));

      // Build current deck list string from deck cards
      const currentCards = deck.cards || [];
      const currentDeckList = currentCards.map(c => {
        const card = c.card;
        const qty = c.quantity;
        const edition = card.edition?.editioncode || '';
        const categories = c.categories?.length ? ` [${c.categories.join(', ')}]` : '';
        return `${qty}x ${card.oracleCard.name} (${edition})${categories}`;
      }).join('\n');

      const cardActions = [];
      const warnings = [];
      let diffResult = { toAdd: [], cardErrors: [] };

      // Real cards to add: resolve names via the diff endpoint.
      if (hasCardLines((cards_to_add || ''))) {
        server.sendLoggingMessage({ level: 'info', data: 'Computing diff...' });
        diffResult = await archidekt.computeDiff(
          accessToken,
          currentDeckList,
          (cards_to_add || '')
        );

        for (const item of diffResult.toAdd || []) {
          cardActions.push(archidekt.createAddCardAction({
            cardId: String(item.card.id),
            quantity: item.quantity,
            categories: item.categories || [],
            modifier: item.modifier || 'Normal',
          }));
        }
      }

      // Real cards to remove: find them in the current deck by name.
      if (hasCardLines((cards_to_remove || ''))) {
        for (const rawLine of (cards_to_remove || '').split('\n')) {
          const line = rawLine.trim();
          if (!line || line.startsWith('#')) continue;

          // Parse line like "2 Sol Ring" or "1x Lightning Bolt"
          const match = line.match(/^(\d+)x?\s+(.+?)(?:\s+\([\w]+\))?(?:\s+\[.+\])?$/i);
          if (!match) continue;

          const qty = parseInt(match[1], 10);
          const cardName = match[2].trim();

          // Find this card in the current deck
          const deckCard = currentCards.find(c =>
            c.card.oracleCard.name.toLowerCase() === cardName.toLowerCase()
          );

          if (deckCard) {
            const currentQty = deckCard.quantity || 1;
            if (qty >= currentQty) {
              // Removing the whole stack: "remove" deletes the deck relation.
              cardActions.push(archidekt.createRemoveCardAction({
                cardId: String(deckCard.card.id),
                deckRelationId: String(deckCard.id),
                quantity: currentQty,
                categories: deckCard.categories || [],
                modifier: deckCard.modifier || 'Normal',
              }));
            } else {
              // Partial removal: "remove" would wipe the whole relation, so
              // "modify" the relation down to the remaining quantity instead.
              cardActions.push(archidekt.createModifyCardAction({
                cardId: String(deckCard.card.id),
                deckRelationId: String(deckCard.id),
                quantity: currentQty - qty,
                categories: deckCard.categories || [],
                modifier: deckCard.modifier || 'Normal',
              }));
            }
          } else {
            warnings.push(`Card not found in deck: ${cardName}`);
          }
        }
      }

      if (cardActions.length === 0) {
        let text = 'No valid card changes to make.';
        if (warnings.length > 0) {
          text += `\n\nWarnings:\n${warnings.map(w => `- ${w}`).join('\n')}`;
        }
        return {
          content: [{ type: 'text', text }],
        };
      }

      server.sendLoggingMessage({ level: 'info', data: `Applying ${cardActions.length} card changes...` });

      // Apply the changes
      const result = await archidekt.modifyCards(accessToken, deck_id, cardActions);

      // Fetch updated deck for card count and legality check
      const updatedDeck = await archidekt.getDeck(accessToken, deck_id);
      const totalCards =
        (updatedDeck.cards || []).reduce((sum, c) => sum + c.quantity, 0);

      // Build summary
      const added = result.add?.length || 0;
      // "modify" actions here are always partial removals (stack reductions).
      const removed = cardActions.filter(a => a.action === 'remove' || a.action === 'modify').length;

      let summary = `Updated deck ${deck_id}:\n`;
      if (added > 0) summary += `- Added ${added} card(s)\n`;
      if (removed > 0) summary += `- Removed ${removed} card(s)\n`;
      summary += `- Total: ${totalCards} cards`;

      const allWarnings = [...warnings, ...(diffResult.cardErrors || [])];
      if (allWarnings.length > 0) {
        summary += `\n\nWarnings:\n${allWarnings.map(e => `- ${e}`).join('\n')}`;
      }

      // Check for newly introduced legality issues
      const issuesAfter = getLegalityIssues(updatedDeck.cards || [], updatedDeck.deckFormat);
      const newIssues = issuesAfter.filter(i => !issuesBefore.has(i));
      if (newIssues.length > 0) {
        summary += `\n\nLegality Issues Introduced:\n${newIssues.map(i => `- ${i}`).join('\n')}`;
      }

      return {
        content: [{ type: 'text', text: summary }],
      };
    } catch (error) {
      server.sendLoggingMessage({ level: 'error', data: `Update deck error: ${error.message}` });
      return {
        content: [{ type: 'text', text: `Failed to update deck: ${error.message}` }],
        isError: true,
      };
    }
  }

  // lookup_cards
  if (name === 'lookup_cards') {
    const cardNamesInput = args.card_names;

    if (!cardNamesInput || !cardNamesInput.trim()) {
      return {
        content: [{ type: 'text', text: 'Please provide at least one card name.' }],
        isError: true,
      };
    }

    // Parse newline-separated list
    const cardNames = cardNamesInput.split('\n').map(l => l.trim()).filter(l => l);

    if (cardNames.length === 0) {
      return {
        content: [{ type: 'text', text: 'Please provide at least one card name.' }],
        isError: true,
      };
    }

    try {
      server.sendLoggingMessage({ level: 'info', data: `Looking up ${cardNames.length} card(s)...` });

      const { found, notFound } = await scryfall.lookupCollection(cardNames);

      if (found.length === 0) {
        return {
          content: [{ type: 'text', text: `No cards found for: ${cardNames.join(', ')}` }],
        };
      }

      // Format each card concisely
      let output = '';
      for (const card of found) {
        output += `## ${card.name}\n`;
        output += `${card.mana_cost || 'No mana cost'} · ${card.type_line}\n`;
        if (card.oracle_text) {
          output += `${card.oracle_text}\n`;
        }
        if (card.power && card.toughness) {
          output += `**${card.power}/${card.toughness}**\n`;
        }
        if (card.loyalty) {
          output += `Loyalty: ${card.loyalty}\n`;
        }
        output += '\n';
      }

      if (notFound.length > 0) {
        output += `---\nNot found: ${notFound.join(', ')}\n`;
      }

      return {
        content: [{ type: 'text', text: output.trim() }],
      };
    } catch (error) {
      server.sendLoggingMessage({ level: 'error', data: `Lookup cards error: ${error.message}` });
      return {
        content: [{ type: 'text', text: `Failed to look up cards: ${error.message}` }],
        isError: true,
      };
    }
  }

  // search_cards
  if (name === 'search_cards') {
    const { query, limit = 20, page = 1, order = 'name', include_text = false, format = 'commander' } = args;

    if (!query || !query.trim()) {
      return {
        content: [{ type: 'text', text: 'Please provide a search query.' }],
        isError: true,
      };
    }

    // Build full query with format filter
    let fullQuery = query.trim();
    if (format && format.toLowerCase() !== 'all') {
      fullQuery += ` format:${format}`;
    }

    const maxResults = Math.min(limit, 175);
    const offset = (page - 1) * maxResults;

    try {
      server.sendLoggingMessage({ level: 'info', data: `Searching: ${fullQuery} (page ${page}, offset ${offset}, order: ${order})` });

      const result = await scryfall.searchPaginated(fullQuery, { offset, limit: maxResults, order });

      if (!result.cards || result.cards.length === 0) {
        if (offset > 0) {
          return {
            content: [{ type: 'text', text: `No more results. Total: ${result.totalCards}` }],
          };
        }
        return {
          content: [{ type: 'text', text: `No cards found for query: ${fullQuery}` }],
        };
      }

      const cards = result.cards;
      const totalFound = result.totalCards;
      const startNum = offset + 1;
      const endNum = offset + cards.length;

      // Format results
      let output = `Found ${totalFound} card(s). Showing ${startNum}-${endNum}:\n\n`;

      for (const card of cards) {
        output += `**${card.name}** · ${card.mana_cost || 'No cost'} · ${card.type_line}\n`;
        if (include_text && card.oracle_text) {
          output += `${card.oracle_text}\n`;
        }
        if (include_text) {
          output += '\n';
        }
      }

      if (result.hasMore) {
        output += `\n---\nMore results available. Use page=${page + 1} to see next page.`;
      }

      return {
        content: [{ type: 'text', text: output.trim() }],
      };
    } catch (error) {
      server.sendLoggingMessage({ level: 'error', data: `Search cards error: ${error.message}` });
      return {
        content: [{ type: 'text', text: `Failed to search cards: ${error.message}` }],
        isError: true,
      };
    }
  }

  return {
    content: [{ type: 'text', text: `Unknown tool: ${name}` }],
    isError: true,
  };
});

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error('Command Tower MCP Server running');
}

main().catch(console.error);
