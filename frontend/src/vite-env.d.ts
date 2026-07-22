/// <reference types="vite/client" />
// Sem esta referência, `bun run typecheck` acusa os imports de .png/.svg como
// módulo inexistente — e o typecheck é o único passo que pega erro de
// referência, já que `vite build` NÃO checa tipos (22/07: uma variável removida
// passou pelo build e deixou a tela de Melhor Horário em branco).
