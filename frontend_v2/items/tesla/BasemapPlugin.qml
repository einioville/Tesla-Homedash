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
    // The plugin reads every built-in type's provider file from here; the others are missing,
    // which marks those types invalid quietly and without a network fetch.
    PluginParameter { name: "osm.mapping.providersrepository.address"; value: "qrc:/config/map-providers/" }
    // The api-key is in the URL, so it comes from AppConfig and never lives in a committed file.
    // The OSM plugin substitutes %x/%y/%z positionally, so MML's z/y/x template works.
    PluginParameter { name: "osm.mapping.host"; value: App.mapTilesUrl }
    PluginParameter { name: "osm.mapping.custom.mapcopyright"; value: App.mapAttribution }
}
