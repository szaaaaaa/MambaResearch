export type SettingsCategoryId =
  | 'general'
  | 'models'
  | 'conversation'
  | 'tools'
  | 'appearance'
  | 'data'
  | 'security'
  | 'experiment'
  | 'knowledge-graph'
  | 'review'
  | 'about';

export interface UiPreferences {
  theme: 'system' | 'light';
  density: 'comfortable' | 'compact';
  chatWidth: 'standard' | 'wide';
  messageFont: 'base' | 'large';
  showWelcomeHints: boolean;
}
