cmake_minimum_required(VERSION 3.16)

project(frontend_v2 VERSION 0.1 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Without this, AUTOMOC ignores .hh headers (the project's header extension),
# so Q_OBJECT classes in core/*.hh never get moc'd → link errors on the
# meta-object symbols. CMP0100 (CMake 3.18+) opts .hh/.h++ into AUTOMOC.
cmake_policy(SET CMP0100 NEW)

find_package(Qt6 REQUIRED COMPONENTS Quick Network Concurrent Svg Location Positioning QuickControls2 Core5Compat Graphs LabsFolderListModel)

qt_standard_project_setup(REQUIRES 6.11)

# The C++ data/transport layer in core/ uses Q_OBJECT / Q_PROPERTY — needs AUTOMOC.
set(CMAKE_AUTOMOC ON)

# Some sources contain UTF-8 literals (e.g. the °C unit in the generated Tesla
# code); make MSVC read sources as UTF-8 rather than the system code page.
add_compile_options($<$<CXX_COMPILER_ID:MSVC>:/utf-8>)

# --- Compiler cache (sccache / ccache) -------------------------------------
# Reuse compiled objects across builds AND across git worktrees, so a fresh
# worktree's "clean" rebuild is mostly cache hits. Auto-enabled when sccache or
# ccache is on PATH; a plain no-op otherwise. On MSVC the cache can only reuse an
# object when its debug info is embedded (/Z7) rather than written to a shared
# .pdb (/Zi), so rewrite the default debug flags accordingly.
find_program(COMPILER_CACHE NAMES sccache ccache)
if(COMPILER_CACHE)
    set(CMAKE_CXX_COMPILER_LAUNCHER "${COMPILER_CACHE}")
    set(CMAKE_C_COMPILER_LAUNCHER "${COMPILER_CACHE}")
    if(MSVC)
        foreach(cfg DEBUG RELWITHDEBINFO)
            string(REPLACE "/Zi" "/Z7" CMAKE_CXX_FLAGS_${cfg} "${CMAKE_CXX_FLAGS_${cfg}}")
            string(REPLACE "/ZI" "/Z7" CMAKE_CXX_FLAGS_${cfg} "${CMAKE_CXX_FLAGS_${cfg}}")
        endforeach()
    endif()
    message(STATUS "Compiler cache enabled: ${COMPILER_CACHE}")
endif()

qt_add_executable(appfrontend_v2
    main.cpp
    core/protocol.hh
    core/logger.hh
    core/logger.cpp
    core/serverclient.hh
    core/serverclient.cpp
    core/appconfig.hh
    core/appconfig.cpp
    core/dotenv.hh
    core/dotenv.cpp
    core/settings.hh
    core/settings.cpp
    core/idlewatcher.hh
    core/idlewatcher.cpp
    core/tesla/tesladata_gen.hh
    core/tesla/tesladata_gen.cpp
    core/tesla/tesladata.hh
    core/tesla/tesladata.cpp
    core/tesla/teslahistory.hh
    core/tesla/teslahistory.cpp
    core/trip/tripsdata.hh
    core/trip/tripsdata.cpp
    core/charging/chargingdata.hh
    core/charging/chargingdata.cpp
    core/media/mediaimagecache.hh
    core/media/mediaimageprovider.hh
    core/media/mediadata.hh
    core/media/mediadata.cpp
    core/weather/weatherforecastmodel.hh
    core/weather/weatherforecastmodel.cpp
    core/weather/weatherdata.hh
    core/weather/weatherdata.cpp
    core/notification/notificationhandler.hh
    core/notification/notificationhandler.cpp
)

# Theme is a QML singleton: the pragma in app/Theme.qml plus this source
# property are both required so the `singleton` line is written to qmldir.
# Must be set before qt_add_qml_module().
set_source_files_properties(app/Theme.qml PROPERTIES QT_QML_SINGLETON_TYPE TRUE)

qt_add_qml_module(appfrontend_v2
    URI frontend_v2
    QML_FILES
        Main.qml
        app/ViewController.qml
        app/Theme.qml
        views/DashboardView.qml
        views/HistoryView.qml
        views/MediaView.qml
        views/MapView.qml
        views/TripsView.qml
        views/ChargingView.qml
        views/SettingsView.qml
        items/settings/SettingRow.qml
        items/settings/SettingSwitch.qml
        items/settings/SettingSlider.qml
        items/settings/SettingNumber.qml
        items/settings/SettingAction.qml
        items/settings/SettingText.qml
        items/settings/SettingSelect.qml
        items/settings/SettingsSidebar.qml
        items/settings/SettingsPane.qml
        items/trip/TripMap.qml
        items/trip/TripComboBox.qml
        items/trip/WeekSelector.qml
        items/trip/TripSelector.qml
        items/trip/TripMarker.qml
        items/trip/TripStatCard.qml
        items/trip/TripStatsGrid.qml
        items/trip/TripPropertySelector.qml
        items/trip/TripGraphCard.qml
        items/charging/ChargingGraphCard.qml
        items/charging/ChargingStatsGrid.qml
        items/charging/ChargingLiveCard.qml
        items/history/PropertySelector.qml
        items/history/RangeSelector.qml
        items/history/DateTimePicker.qml
        items/history/HistoryGraph.qml
        items/history/GraphPrewarm.qml
        items/luna/Luna.qml
        items/util/Dock.qml
        items/util/DockIcon.qml
        items/util/HomeIndicator.qml
        items/util/TextButton.qml
        items/util/GradientCard.qml
        items/util/TintedIcon.qml
        items/util/GlowIcon.qml
        items/util/RoundedImage.qml
        items/util/GlassPanel.qml
        items/util/NotificationLayer.qml
        items/util/ScreenSaver.qml
        items/tesla/DataEntry.qml
        items/tesla/DataEntryList.qml
        items/tesla/TemperatureCard.qml
        items/tesla/ClimateStarter.qml
        items/tesla/SeatWidget.qml
        items/tesla/SteeringWidget.qml
        items/tesla/ClimateCard.qml
        items/tesla/TeslaMap.qml
        items/media/MediaPlayerCard.qml
        items/media/MediaCover.qml
        items/media/MediaTransport.qml
        items/media/MediaSeekBar.qml
        items/weather/WeatherForecastCard.qml
        items/weather/CurrentWeatherCard.qml
        items/weather/MainWeather.qml
)

# Qt for iOS sets MACOSX_BUNDLE_GUI_IDENTIFIER automatically since Qt 6.1.
# If you are developing for iOS or macOS you should consider setting an
# explicit, fixed bundle identifier manually though.
set_target_properties(appfrontend_v2 PROPERTIES
#    MACOSX_BUNDLE_GUI_IDENTIFIER com.example.appfrontend_v2
    MACOSX_BUNDLE_BUNDLE_VERSION ${PROJECT_VERSION}
    MACOSX_BUNDLE_SHORT_VERSION_STRING ${PROJECT_VERSION_MAJOR}.${PROJECT_VERSION_MINOR}
    MACOSX_BUNDLE TRUE
    WIN32_EXECUTABLE TRUE
)

# Includes resolve as "core/..." from main.cpp and as siblings within core/.
target_include_directories(appfrontend_v2 PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})

# Bake the source directory so AppConfig can locate the repo-root .env even when
# Qt Creator builds the exe outside the source tree (shadow build) — the cwd/exe
# walk-up alone never reaches it. Used only to find .env; real environment
# variables still take precedence, so this absolute dev path is harmless when the
# directory no longer exists on a deployment target.
target_compile_definitions(appfrontend_v2 PRIVATE
    FRONTEND_V2_SOURCE_DIR="${CMAKE_CURRENT_SOURCE_DIR}")

target_link_libraries(appfrontend_v2
    PRIVATE Qt6::Quick Qt6::Network Qt6::Concurrent Qt6::Svg Qt6::Location Qt6::Positioning
            Qt6::QuickControls2 Qt6::Core5Compat Qt6::Graphs Qt6::LabsFolderListModel
)

# Static resources (font + icons) exposed at :/resources/... — the same paths
# the Widgets frontend used, so QML references qrc:/resources/icons/... and the
# application font (main.cpp) loads identically. Kept out of the QML module so
# the prefix stays /resources rather than /qt/qml/frontend_v2.
qt_add_resources(appfrontend_v2 "app_resources"
    PREFIX "/"
    FILES
        resources/fonts/gothamrnd_medium.otf
        resources/icons/app.svg
        resources/icons/arrow.svg
        resources/icons/arrow_left.svg
        resources/icons/arrow_right.svg
        resources/icons/charger.svg
        resources/icons/chart_line.svg
        resources/icons/cooling.png
        resources/icons/greenshadow.png
        resources/icons/heating.png
        resources/icons/home.svg
        resources/icons/link.svg
        resources/icons/location.svg
        resources/icons/music.svg
        resources/icons/minus.svg
        resources/icons/pause.svg
        resources/icons/play.svg
        resources/icons/price.svg
        resources/icons/plus.svg
        resources/icons/power_off.svg
        resources/icons/power_on.svg
        resources/icons/power_pending.svg
        resources/icons/redshadow.png
        resources/icons/restart.svg
        resources/icons/screensaver.png
        resources/icons/seat.svg
        resources/icons/settings.svg
        resources/icons/skip_backward.svg
        resources/icons/skip_forward.svg
        resources/icons/steering.svg
        resources/icons/trip.svg
        resources/icons/yellowshadow.png
        resources/icons/weather/clouds.svg
        resources/icons/weather/rain.svg
        resources/icons/weather/thermometer.svg
        resources/icons/weather/wind.svg
        resources/Luna/stationary.png
        resources/Luna/eating_1.png
        resources/Luna/eating_2.png
        resources/Luna/eating_3.png
        resources/Luna/eating_4.png
        resources/Luna/sitting_1.png
        resources/Luna/sleeping_1.png
        resources/Luna/sniffing_1.png
        resources/Luna/sniffing_2.png
        resources/Luna/sniffing_3.png
        resources/Luna/walking_1.png
        resources/Luna/walking_2.png
        resources/Luna/walking_3.png
        resources/Luna/walking_4.png
        resources/Luna/walking_5.png
        config/notifications.json
        config/settings.json
)

# Developer convenience: regenerate the Tesla data layer from the registry.
# The generated files are committed, so a normal build never needs Python.
find_package(Python3 COMPONENTS Interpreter QUIET)
if(Python3_FOUND)
    add_custom_target(regen_tesla_data
        COMMAND ${Python3_EXECUTABLE}
                ${CMAKE_CURRENT_SOURCE_DIR}/core/tesla/generate_tesladata.py
                ${CMAKE_CURRENT_SOURCE_DIR}/core/tesla/tesla_properties.json
                ${CMAKE_CURRENT_SOURCE_DIR}/core/tesla/tesladata_gen.hh
                ${CMAKE_CURRENT_SOURCE_DIR}/core/tesla/tesladata_gen.cpp
        COMMENT "Regenerating Tesla data layer from tesla_properties.json"
        VERBATIM
    )
endif()

install(TARGETS appfrontend_v2
    BUNDLE DESTINATION .
    LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
    RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
)
