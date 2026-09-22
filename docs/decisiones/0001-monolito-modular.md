# Decisión 0001: Monolito modular

**Fecha:** 2026-09-21
**Estado:** Aceptada

## Contexto

Necesitamos una arquitectura para un marketplace multi-vendedor que arrancará pequeño, pero que podría crecer mucho. La opción natural de "microservicios desde el día 1" añade mucha complejidad operativa (orquestación, red, despliegues, consistencia distribuida) que hoy no necesitamos.

## Decisión

Construir un **monolito modular**: una sola aplicación desplegable, dividida en módulos de negocio con fronteras claras y capas internas (`api → service → repository → models`).

Reglas de frontera:
- Cada módulo es dueño de sus tablas. Ningún módulo lee/escribe las tablas de otro directamente.
- La comunicación entre módulos se hace solo por los servicios públicos del otro módulo o por eventos internos de dominio.
- La lógica de negocio vive en `service`, nunca en las rutas.

## Consecuencias

**Positivas:**
- Despliegue y desarrollo simples (un solo proceso, una sola BD).
- Fronteras claras permiten extraer un módulo a microservicio más adelante sin reescribirlo.
- Menor costo operativo inicial (YAGNI).

**Negativas / a vigilar:**
- Riesgo de acoplamiento si no se respetan las fronteras (se mitiga con revisión de código y las reglas de `.clinerules`).
- Escala vertical como límite a corto plazo; si el tráfico lo exige, se extraen módulos puntuales.

## Alternativas descartadas

- **Microservicios desde el inicio:** demasiada complejidad operativa para la etapa actual; se puede llegar a ellos de forma incremental.
- **Monolito "big ball of mud" (sin módulos):** simple al inicio pero imposible de mantener o escalar; no ofrece camino de evolución.
