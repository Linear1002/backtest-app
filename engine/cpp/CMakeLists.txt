# engine/cpp/CMakeLists.txt(M0)
# docs/cpp/README.md の M0 のひな形。M1 で .cpp が増えたら「M1 以降」の形に書き換える。
add_executable(backtest_cli src/main.cpp)
target_compile_features(backtest_cli PRIVATE cxx_std_17)
