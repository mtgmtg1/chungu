// @ts-check
import {themes as prismThemes} from 'prism-react-renderer';

/** @type {import('@docusaurus/types').Config} */
const config = {
  title: 'Chungu API',
  tagline: 'PDF, images, audio, video → structured tables',
  favicon: 'img/favicon.svg',

  future: {
    v4: true,
  },

  url: 'https://chungu.app',
  baseUrl: '/docs/',

  onBrokenLinks: 'warn',

  i18n: {
    defaultLocale: 'en',
    locales: ['en', 'ko', 'ja'],
    localeConfigs: {
      en: { label: 'English', htmlLang: 'en' },
      ko: { label: '한국어', htmlLang: 'ko' },
      ja: { label: '日本語', htmlLang: 'ja' },
    },
  },

  presets: [
    [
      'classic',
      /** @type {import('@docusaurus/preset-classic').Options} */
      ({
        docs: {
          sidebarPath: './sidebars.js',
          editUrl: undefined,
          routeBasePath: '/',
        },
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      }),
    ],
  ],

  themes: [
    [
      '@easyops-cn/docusaurus-search-local',
      {
        hashed: true,
        indexDocs: true,
        indexBlog: false,
        indexPages: false,
        language: ['en', 'ko', 'ja'],
        docsRouteBasePath: '/',
      },
    ],
  ],

  themeConfig:
    /** @type {import('@docusaurus/preset-classic').ThemeConfig} */
    ({
      colorMode: {
        respectPrefersColorScheme: true,
      },
      navbar: {
        title: 'Chungu API',
        logo: {
          alt: 'Chungu',
          src: 'img/logo.svg',
        },
        items: [
          {
            type: 'docSidebar',
            sidebarId: 'docsSidebar',
            position: 'left',
            label: 'Docs',
          },
          {
            type: 'docSidebar',
            sidebarId: 'apiReferenceSidebar',
            position: 'left',
            label: 'API Reference',
          },
          {
            type: 'docSidebar',
            sidebarId: 'aiPromptsSidebar',
            position: 'left',
            label: 'AI Prompts',
          },
          {
            type: 'localeDropdown',
            position: 'right',
          },
          {
            href: '../../developer',
            label: 'Developer Portal',
            position: 'right',
          },
        ],
      },
      footer: {
        style: 'dark',
        links: [
          {
            title: 'Documentation',
            items: [
              { label: 'Quick Start', to: '/quickstart' },
              { label: 'Authentication', to: '/authentication' },
              { label: 'API Reference', to: '/api-reference/jobs/upload' },
            ],
          },
          {
            title: 'Resources',
            items: [
              { label: 'AI Prompts', to: '/ai-prompts/full-pipeline-prompt' },
              { label: 'Pricing', to: '/pricing' },
              { label: 'Changelog', to: '/changelog' },
            ],
          },
          {
            title: 'Links',
            items: [
              { label: 'Developer Portal', href: '../../developer' },
              { label: 'Swagger / OpenAPI', href: '../../api/v1/docs' },
            ],
          },
        ],
        copyright: `Copyright © ${new Date().getFullYear()} Chungu. Built with Docusaurus.`,
      },
      prism: {
        theme: prismThemes.github,
        darkTheme: prismThemes.dracula,
        additionalLanguages: ['bash', 'json', 'python', 'yaml'],
      },
    }),
};

export default config;
