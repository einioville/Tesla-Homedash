import QtLocation
import frontend_v2

// The plugin every imagery map is built on (TeslaMap, TripMap, the Koti dialog's), with two
// map types: MML's 0.5 m orthophoto as the custom type, when AppConfig has its key, and EOX's
// keyless Sentinel-2 cloudless (~10 m, the whole world) as the satellite type, from the
// provider file bundled at qrc:/config/map-providers/satellite (zoom 18 at most: EOX has no
// 19). BasemapSwitch picks between them. The two types' tiles are cached apart: the OSM
// plugin names a cached tile by its map type's id.
Plugin {
    name: "osm"

    PluginParameter { name: "osm.useragent"; value: "Tesla-Homedash/1.0" }
    // The plugin reads every built-in type's provider file from here. Only the satellite type's
    // is bundled: the others fall back to Qt's built-in servers, which BasemapSwitch never picks.
    PluginParameter { name: "osm.mapping.providersrepository.address"; value: "qrc:/config/map-providers/" }
    // The api-key is in the URL, so it comes from AppConfig and never lives in a committed file.
    // The OSM plugin substitutes %x/%y/%z positionally, so MML's z/y/x template works.
    PluginParameter { name: "osm.mapping.host"; value: App.mapTilesUrl }
    PluginParameter { name: "osm.mapping.custom.mapcopyright"; value: App.mapAttribution }
    // Every map's tiles share one cache folder. Each map's cache reads the whole folder when it
    // starts and deletes down to its size, first in name order, and EOX's tiles (type 2) sort
    // ahead of MML's (8): at Qt's 50 MiB, MML's 0.5 m imagery deleted EOX's on every start.
    PluginParameter { name: "osm.mapping.cache.disk.size"; value: 300 * 1024 * 1024 }
    // Qt never expires a cached tile; the Options view's cache clear deletes this folder.
    PluginParameter { name: "osm.mapping.cache.directory"; value: App.mapTileCacheDir }
}
