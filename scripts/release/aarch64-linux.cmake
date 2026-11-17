# The compiler half of the arm64 cross build scripts/release.sh runs. Qt's own toolchain file
# (the arm64 kit's lib/cmake/Qt6/qt.toolchain.cmake) loads this one as its
# QT_CHAINLOAD_TOOLCHAIN_FILE, and QT_HOST_PATH points it at the build host's kit for moc,
# qmlcachegen, rcc and qsb.
#
# The sysroot comes from the environment rather than a cache variable because CMake re-reads a
# toolchain file for every try_compile, where only the environment is sure to reach it.
set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR aarch64)

set(CMAKE_C_COMPILER aarch64-linux-gnu-gcc)
set(CMAKE_CXX_COMPILER aarch64-linux-gnu-g++)
set(CMAKE_SYSROOT "$ENV{TESLA_HOMEDASH_SYSROOT}")
if(NOT IS_DIRECTORY "${CMAKE_SYSROOT}/usr/lib/aarch64-linux-gnu")
    message(FATAL_ERROR "TESLA_HOMEDASH_SYSROOT is not an arm64 sysroot: '${CMAKE_SYSROOT}' "
                        "(scripts/release/toolchain.sh makes one)")
endif()

set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)

# find_package(Qt6) asks pkg-config for some system libraries (xkbcommon, wayland, …), which
# would otherwise answer with the build host's own x86_64 ones.
set(ENV{PKG_CONFIG_DIR} "")
set(ENV{PKG_CONFIG_SYSROOT_DIR} "${CMAKE_SYSROOT}")
set(ENV{PKG_CONFIG_LIBDIR}
    "${CMAKE_SYSROOT}/usr/lib/aarch64-linux-gnu/pkgconfig:${CMAKE_SYSROOT}/usr/share/pkgconfig")
