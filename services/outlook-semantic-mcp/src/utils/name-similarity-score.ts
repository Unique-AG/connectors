// Jaro-Winkler is designed for name matching: it rewards common prefixes and handles
// transpositions better than edit-distance metrics like Levenshtein.
import { jaroWinkler } from './jaro-winkler';
// Scores a contact name against the query using Jaro-Winkler.
// Compares the query against the full name and each individual token, taking the maximum.
// This handles partial queries (e.g. "Smith" matching "John Smith").
export function nameSimilarity(query: string, contactName: string): number {
  query = query.toLowerCase();
  contactName = contactName.toLowerCase();
  return Math.max(
    jaroWinkler(query, contactName),
    ...contactName.split(/\s+/).map((token) => jaroWinkler(query, token)),
  );
}
