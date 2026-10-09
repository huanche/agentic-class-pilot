declare module 'word-extractor' {
  interface WordDocument {
    getBody(): string;
    getTextboxes(options?: { includeHeadersAndFooters?: boolean; includeBody?: boolean }): string;
    getFootnotes(): string;
    getEndnotes(): string;
  }
  export default class WordExtractor {
    extract(source: Buffer | string): Promise<WordDocument>;
  }
}
