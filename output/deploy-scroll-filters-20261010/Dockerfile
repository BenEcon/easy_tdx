FROM easy-tdx:tracking-history-signals-20261010
USER root
COPY --chown=10001:10001 dist/ /opt/easy_tdx/web-ui/dist/
COPY --chown=10001:10001 dist/ /usr/local/lib/python3.12/site-packages/easy_tdx/web/dist/
USER easytdx
LABEL org.easy-tdx.release="scroll-filters-20261010"
