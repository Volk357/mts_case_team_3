import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "coverage", "src/components/ui"] },
  {
    files: ["**/*.{ts,tsx}"],
    extends: [js.configs.recommended, ...tseslint.configs.recommendedTypeChecked],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.flat.recommended.rules,
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
      "no-restricted-syntax": [
        "error",
        {
          selector: "TSInterfaceDeclaration[id.name='Finding']",
          message:
            "Import Finding from @/api/contracts; its source of truth is contracts/review-result.schema.json.",
        },
        {
          selector: "TSTypeAliasDeclaration[id.name='Finding']",
          message:
            "Import Finding from @/api/contracts; its source of truth is contracts/review-result.schema.json.",
        },
      ],
    },
  },
);
