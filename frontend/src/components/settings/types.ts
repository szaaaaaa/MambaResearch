export type SettingsCategoryId =
  | 'general'
  | 'models'
  | 'conversation'
  | 'tools'
  | 'appearance'
  | 'data'
  | 'security'
  | 'about';

export interface UiPreferences {
  theme: 'system' | 'light';
  density: 'comfortable' | 'compact';
  chatWidth: 'standard' | 'wide';
  messageFont: 'base' | 'large';
  showWelcomeHints: boolean;
}
