// @ts-check

/** @type {import('@docusaurus/plugin-content-docs').SidebarsConfig} */
const sidebars = {
  docsSidebar: [
    'intro',
    'quickstart',
    'authentication',
    'pricing',
    {
      type: 'category',
      label: 'Core Concepts',
      items: [
        'core-concepts/job-lifecycle',
        'core-concepts/file-formats',
        'core-concepts/output-formats',
        'core-concepts/pipelines',
        'core-concepts/extraction-options',
        'core-concepts/errors',
      ],
    },
    'sdks-and-tools',
    'changelog',
  ],

  apiReferenceSidebar: [
    {
      type: 'category',
      label: 'Account',
      items: [
        'api-reference/account/get-account',
        'api-reference/account/get-pricing',
        'api-reference/account/get-usage',
        'api-reference/account/get-transactions',
        'api-reference/account/get-payments',
      ],
    },
    {
      type: 'category',
      label: 'API Keys',
      items: [
        'api-reference/api-keys/create-key',
        'api-reference/api-keys/list-keys',
        'api-reference/api-keys/delete-key',
        'api-reference/api-keys/rotate-key',
        'api-reference/api-keys/get-key-usage',
      ],
    },
    {
      type: 'category',
      label: 'Jobs',
      items: [
        'api-reference/jobs/upload',
        'api-reference/jobs/confirm',
        'api-reference/jobs/get-job',
        'api-reference/jobs/list-jobs',
        'api-reference/jobs/download',
        'api-reference/jobs/convert',
      ],
    },
  ],

  aiPromptsSidebar: [
    'ai-prompts/full-pipeline-prompt',
    'ai-prompts/endpoint-prompts',
  ],
};

export default sidebars;
