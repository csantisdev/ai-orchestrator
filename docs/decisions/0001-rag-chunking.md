# Decisión 0001: chunking RAG de 1500 caracteres

Fecha: 2026-06-22

Estado: aceptada

## Contexto

La indexación documental usaba chunks de 800 caracteres con 100 caracteres
de solapamiento. Ese tamaño fragmentaba código y documentación en unidades
pequeñas, aumentando la cantidad de vectores y reduciendo el contexto local
disponible en cada resultado.

## Decisión

Usar chunks de 1500 caracteres con 200 caracteres de solapamiento.

`chunk_text` conserva esos valores como defaults, permite parametrizarlos para
pruebas o usos específicos y rechaza configuraciones inválidas donde el tamaño
no sea positivo o el solapamiento sea igual o mayor al tamaño.

Los cortes priorizan un salto de línea ubicado en la segunda mitad del chunk.
Si no existe, se aplica el límite de caracteres.

## Consecuencias

- Se generan menos vectores por documento.
- Cada resultado conserva más contexto de código o prosa.
- El solapamiento mantiene continuidad entre chunks consecutivos.
- Cambiar estos valores requiere reindexar el proyecto.
- El umbral de distancia de recuperación (`1.4`) es una decisión independiente
  y debe evaluarse con métricas de relevancia.
