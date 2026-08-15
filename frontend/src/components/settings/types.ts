export type SettingsCategoryId =
  | 'project'
  | 'mcp'
  | 'credentials'
  | 'skills'
  | 'appearance'
  | 'about';

export interface UiPreferences {
  theme: 'system' | 'light';
  density: 'comfortable' | 'compact';
  chatWidth: 'standard' | 'wide';
  messageFont: 'base' | 'large';
  showWelcomeHints: boolean;
}
