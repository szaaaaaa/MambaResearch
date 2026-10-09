import {StrictMode} from 'react';
import {createRoot} from 'react-dom/client';
import App from './App.tsx';
import './styles/tokens.css';
import './styles/chat.css';
import './styles/settings.css';
import './index.css';
import { initializeWorkbench } from './api/workbench';

initializeWorkbench().then(() => {
  const root = createRoot(document.getElementById('root')!);
  root.render(<StrictMode><App /></StrictMode>);
  window.addEventListener('mambaresearch-teardown', () => root.unmount(), { once: true });
  window.addEventListener('pagehide', () => root.unmount(), { once: true });
}).catch((error) => {
  const root = document.getElementById('root')!;
  root.textContent = `科研工作台连接失败：${error.message}`;
});
