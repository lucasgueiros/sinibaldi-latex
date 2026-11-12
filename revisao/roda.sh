#!/bin/sh
# Revisão Haiku dos dois trechos de medição (Theodicea: essência de Deus + criação), 36 pp., 19 pedaços.
# Anote o /usage antes e depois para medir quanto da sessão de 5h do Pro isto gasta.
cd "$(dirname "$0")/.." || exit 1
for d in essencia-de-deus creacao; do
  python3 tools/revisa_paginas.py revisao/$d/entrada.xml --vol vol2 --saida revisao/$d \
    --volume vol2/vol2.corrigido.xml --paralelo 3
done
