FROM easy-tdx:period-evidence-20261009
USER root
RUN python -m pip install --no-cache-dir "httpx==0.28.1" && python -m pip check
COPY --chown=10001:10001 src/easy_tdx/ /opt/easy_tdx/src/easy_tdx/
COPY --chown=10001:10001 src/easy_tdx/ /usr/local/lib/python3.12/site-packages/easy_tdx/
COPY --chown=10001:10001 dist/ /opt/easy_tdx/web-ui/dist/
COPY --chown=10001:10001 dist/ /usr/local/lib/python3.12/site-packages/easy_tdx/web/dist/
USER easytdx
LABEL org.easy-tdx.release="activity-access-20261009" org.easy-tdx.source="24e11c566a8905a0c7923f9e8ef3faefd12ba71d0dc82ac2433b79ae4b6881a6"
