# Cámara USB del cliente y HTTPS

La cámara pertenece al PC que abre el navegador; no hace falta conectarla al servidor Clarke. El permiso de cámara lo solicita el navegador al pulsar **Abrir cámara** en **Laboratorio de visión**. No se solicita audio.

## Opción configurada: HTTPS local sin dominio

- Web segura: **https://172.19.33.30:8443/#vision**.
- Web HTTP existente: http://172.19.33.30:8080/ (subidas y análisis; la cámara remota necesita un contexto seguro).
- Caddy emite y renueva los certificados mediante su propia autoridad local. No se necesita un dominio público ni abrir el servicio a Internet.
- Cada PC cliente debe confiar una vez en la **raíz pública** de POSTURE. La clave privada permanece en el volumen `posture_caddy_data`; no se distribuye.

### Obtener y comprobar la raíz pública

Desde el acceso HTTP, inicia sesión como administrador, abre **Laboratorio de visión → Cámara USB → Descargar certificado público**. El archivo se llama `POSTURE-root.crt`.

También está en `.runtime/posture-root.crt` del servidor. Para volver a exportarlo:

```bash
./launch_docker certificate
```

El comando imprime la huella SHA-256 de la raíz. Contrástala con la del archivo descargado antes de confiar en él:

```bash
openssl x509 -in POSTURE-root.crt -noout -fingerprint -sha256
```

### Windows (Chrome / Edge)

1. Abre `POSTURE-root.crt` → **Instalar certificado**.
2. Elige **Usuario actual** y almacén **Entidades de certificación raíz de confianza**.
3. Acepta la importación y reinicia el navegador.
4. Abre la dirección HTTPS anterior y permite la cámara para este sitio.

Puede utilizarse `certmgr.msc` para gestionar o retirar la raíz. Firefox puede requerir importarla en sus propias autoridades si no utiliza las del sistema.

### macOS

Importa el certificado en **Acceso a Llaveros**, abre su apartado **Confiar** y selecciona **Confiar siempre** para esta raíz. Reinicia el navegador y abre HTTPS.

### Linux

En Chrome/Chromium, importa el archivo en **Configuración → Privacidad y seguridad → Seguridad → Gestionar certificados → Autoridades**. En Firefox: **Ajustes → Privacidad y seguridad → Certificados → Ver certificados → Autoridades → Importar**; habilita la confianza para identificar sitios web.

En Debian/Ubuntu, para instalarlo además en el almacén del sistema:

```bash
sudo cp POSTURE-root.crt /usr/local/share/ca-certificates/posture-root.crt
sudo update-ca-certificates
```

Reinicia el navegador. Según su almacén de confianza puede seguir siendo necesaria la importación en el propio navegador.

**Continuar a pesar de una advertencia TLS no sustituye instalar la raíz de confianza.** La cámara debe utilizarse desde una página sin errores de certificado.

## Alternativa para pruebas: túnel SSH y localhost

Si el cliente tiene SSH al servidor, puede evitar instalar una raíz local:

```bash
ssh -N -L 18080:127.0.0.1:8080 dmulero@172.19.33.30
```

Mantén esa terminal abierta y visita **http://localhost:18080/#vision** en el cliente. El navegador considera `localhost` un contexto seguro y el tráfico al servidor viaja por el túnel SSH.

## Configuración

`POSTURE_TLS_HOST` en `.env` fija la dirección principal (por defecto `172.19.33.30`), `POSTURE_TLS_PORT` el puerto publicado (8443). Después de cambiarlo, ejecuta `./launch_docker up`. El certificado raíz permanece estable mientras se conserve `caddy_data`.

Usa la dirección principal para entrar por IP: clientes que omiten SNI reciben el certificado de `POSTURE_TLS_HOST`. La dirección Tailscale HTTP anterior permanece disponible; para HTTPS por otra IP principal, configura esa IP como `POSTURE_TLS_HOST`.

Si más adelante se dispone de un dominio, Caddy puede usar una autoridad pública y ya no será necesario instalar la raíz local. Esta entrega mantiene la plataforma alojada en Docker en Clarke.

Referencias: [contextos seguros para cámara](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia), [HTTPS local de Caddy](https://caddyserver.com/docs/automatic-https#local-https).
